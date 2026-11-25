import type { OrbitCamera } from '../camera';
import {
  LAYER_OPTIONS,
  type AerialLayerKey,
  type CaliperResult,
  type LoadedCandidateData,
  type RenderParams,
} from '../types';
import terrainWgsl from '../shaders/terrain.wgsl?raw';
import canopyWgsl from '../shaders/canopy.wgsl?raw';
import overlayWgsl from '../shaders/overlay.wgsl?raw';

const UNIFORM_BYTES = 176;
const OVERLAY_UNIFORM_BYTES = 64;

function layerIdToShaderIndex(id: RenderParams['primaryLayer']): number {
  const found = LAYER_OPTIONS.find((l) => l.id === id);
  return found ? found.shaderIndex : 0;
}

export class WebGpuContext {
  public readonly adapter: GPUAdapter;
  public readonly device: GPUDevice;
  public readonly format: GPUTextureFormat;
  public readonly sampler: GPUSampler;
  public readonly placeholderTex: GPUTexture;

  public readonly terrainBgl: GPUBindGroupLayout;
  public readonly canopyBgl: GPUBindGroupLayout;
  public readonly overlayBgl: GPUBindGroupLayout;

  public readonly terrainPipeline: GPURenderPipeline;
  public readonly canopyPipeline: GPURenderPipeline;
  public readonly overlayPipeline: GPURenderPipeline;

  private constructor(
    adapter: GPUAdapter,
    device: GPUDevice,
    format: GPUTextureFormat
  ) {
    this.adapter = adapter;
    this.device = device;
    this.format = format;

    this.sampler = device.createSampler({
      magFilter: 'linear',
      minFilter: 'linear',
      addressModeU: 'clamp-to-edge',
      addressModeV: 'clamp-to-edge',
    });

    this.placeholderTex = device.createTexture({
      size: [1, 1, 1],
      format: 'rgba8unorm',
      usage:
        GPUTextureUsage.TEXTURE_BINDING |
        GPUTextureUsage.COPY_DST |
        GPUTextureUsage.RENDER_ATTACHMENT,
    });
    device.queue.writeTexture(
      { texture: this.placeholderTex },
      new Uint8Array([32, 36, 44, 255]),
      { bytesPerRow: 4 },
      [1, 1, 1]
    );

    this.terrainBgl = device.createBindGroupLayout({
      label: 'terrain-bgl',
      entries: [
        { binding: 0, visibility: GPUShaderStage.VERTEX | GPUShaderStage.FRAGMENT, buffer: { type: 'uniform' } },
        { binding: 1, visibility: GPUShaderStage.VERTEX | GPUShaderStage.FRAGMENT, buffer: { type: 'read-only-storage' } },
        { binding: 2, visibility: GPUShaderStage.FRAGMENT, sampler: { type: 'filtering' } },
        { binding: 3, visibility: GPUShaderStage.FRAGMENT, texture: { sampleType: 'float' } },
        { binding: 4, visibility: GPUShaderStage.FRAGMENT, texture: { sampleType: 'float' } },
        { binding: 5, visibility: GPUShaderStage.FRAGMENT, texture: { sampleType: 'float' } },
        { binding: 6, visibility: GPUShaderStage.FRAGMENT, texture: { sampleType: 'float' } },
      ],
    });

    this.canopyBgl = device.createBindGroupLayout({
      label: 'canopy-bgl',
      entries: [
        { binding: 0, visibility: GPUShaderStage.VERTEX | GPUShaderStage.FRAGMENT, buffer: { type: 'uniform' } },
        { binding: 1, visibility: GPUShaderStage.VERTEX, buffer: { type: 'read-only-storage' } },
      ],
    });

    this.overlayBgl = device.createBindGroupLayout({
      label: 'overlay-bgl',
      entries: [
        { binding: 0, visibility: GPUShaderStage.VERTEX, buffer: { type: 'uniform' } },
      ],
    });

    const terrainModule = device.createShaderModule({ label: 'terrain.wgsl', code: terrainWgsl });
    const canopyModule = device.createShaderModule({ label: 'canopy.wgsl', code: canopyWgsl });
    const overlayModule = device.createShaderModule({ label: 'overlay.wgsl', code: overlayWgsl });

    this.terrainPipeline = device.createRenderPipeline({
      label: 'terrain-pipeline',
      layout: device.createPipelineLayout({ bindGroupLayouts: [this.terrainBgl] }),
      vertex: { module: terrainModule, entryPoint: 'vs_main' },
      fragment: {
        module: terrainModule,
        entryPoint: 'fs_main',
        targets: [{ format }],
      },
      primitive: { topology: 'triangle-list', cullMode: 'none' },
      depthStencil: {
        format: 'depth24plus',
        depthWriteEnabled: true,
        depthCompare: 'less',
      },
    });

    this.canopyPipeline = device.createRenderPipeline({
      label: 'canopy-pipeline',
      layout: device.createPipelineLayout({ bindGroupLayouts: [this.canopyBgl] }),
      vertex: { module: canopyModule, entryPoint: 'vs_main' },
      fragment: {
        module: canopyModule,
        entryPoint: 'fs_main',
        targets: [{ format }],
      },
      primitive: { topology: 'triangle-list', cullMode: 'none' },
      depthStencil: {
        format: 'depth24plus',
        depthWriteEnabled: true,
        depthCompare: 'less',
      },
    });

    this.overlayPipeline = device.createRenderPipeline({
      label: 'overlay-pipeline',
      layout: device.createPipelineLayout({ bindGroupLayouts: [this.overlayBgl] }),
      vertex: {
        module: overlayModule,
        entryPoint: 'vs_main',
        buffers: [
          {
            arrayStride: 16,
            attributes: [{ shaderLocation: 0, offset: 0, format: 'float32x4' }],
          },
        ],
      },
      fragment: {
        module: overlayModule,
        entryPoint: 'fs_main',
        targets: [{ format }],
      },
      primitive: { topology: 'triangle-list', cullMode: 'none' },
      depthStencil: {
        format: 'depth24plus',
        depthWriteEnabled: true,
        depthCompare: 'less-equal',
      },
    });
  }

  public static async create(): Promise<WebGpuContext> {
    if (!navigator.gpu) {
      throw new Error('WebGPU is not supported in this browser (navigator.gpu missing).');
    }
    const adapter = await navigator.gpu.requestAdapter({ powerPreference: 'high-performance' });
    if (!adapter) {
      throw new Error('No WebGPU adapter found.');
    }
    const device = await adapter.requestDevice();
    const format = navigator.gpu.getPreferredCanvasFormat();
    return new WebGpuContext(adapter, device, format);
  }
}

export class TerrainBenchViewport {
  private readonly gpu: WebGpuContext;
  public readonly canvas: HTMLCanvasElement;
  private readonly context: GPUCanvasContext;

  private readonly uniformBuffer: GPUBuffer;
  private readonly overlayUniformBuffer: GPUBuffer;
  private readonly uniformData = new ArrayBuffer(UNIFORM_BYTES);
  private readonly uniformF32 = new Float32Array(this.uniformData);
  private readonly uniformU32 = new Uint32Array(this.uniformData);

  private depthTex: GPUTexture | null = null;
  private depthW = 0;
  private depthH = 0;

  private gridBuffer: GPUBuffer | null = null;
  private indexBuffer: GPUBuffer | null = null;
  private indexCount = 0;

  private canopyBuffer: GPUBuffer | null = null;
  private canopyCount = 0;

  private aerialTextures: Partial<Record<AerialLayerKey, GPUTexture>> = {};
  private textureFlags: Record<AerialLayerKey, boolean> = {
    ort_USA10: false,
    ort_old10: false,
    gazo1: false,
    seamlessphoto: false,
  };

  private terrainBindGroup: GPUBindGroup | null = null;
  private canopyBindGroup: GPUBindGroup | null = null;
  private overlayBindGroup: GPUBindGroup;

  private overlayVertexBuffer: GPUBuffer | null = null;
  private overlayVertexCount = 0;

  private loadedData: LoadedCandidateData | null = null;

  constructor(gpu: WebGpuContext, canvas: HTMLCanvasElement) {
    this.gpu = gpu;
    this.canvas = canvas;
    const ctx = canvas.getContext('webgpu');
    if (!ctx) {
      throw new Error('Failed to acquire WebGPU canvas context.');
    }
    this.context = ctx;
    this.context.configure({
      device: gpu.device,
      format: gpu.format,
      alphaMode: 'opaque',
    });

    this.uniformBuffer = gpu.device.createBuffer({
      size: UNIFORM_BYTES,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    });

    this.overlayUniformBuffer = gpu.device.createBuffer({
      size: OVERLAY_UNIFORM_BYTES,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST,
    });

    this.overlayBindGroup = gpu.device.createBindGroup({
      layout: gpu.overlayBgl,
      entries: [{ binding: 0, resource: { buffer: this.overlayUniformBuffer } }],
    });
  }

  public uploadCandidateData(data: LoadedCandidateData): void {
    this.loadedData = data;
    const device = this.gpu.device;
    const { nx, ny, n_canopy_pts } = data.pack.header;

    this.gridBuffer?.destroy();
    this.indexBuffer?.destroy();
    this.canopyBuffer?.destroy();
    for (const tex of Object.values(this.aerialTextures)) {
      tex?.destroy();
    }
    this.aerialTextures = {};

    // Upload 10 planar float32 layers
    const gridBytes = data.pack.rawGridBuffer.byteLength;
    this.gridBuffer = device.createBuffer({
      label: 'grid-storage',
      size: Math.max(16, gridBytes + data.coverage.byteLength),
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(
      this.gridBuffer,
      0,
      data.pack.rawGridBuffer.buffer,
      data.pack.rawGridBuffer.byteOffset,
      gridBytes
    );

    device.queue.writeBuffer(this.gridBuffer, gridBytes, data.coverage.buffer, data.coverage.byteOffset, data.coverage.byteLength);

    // Build triangle index buffer for nx * ny grid
    const quadCount = (nx - 1) * (ny - 1);
    const indices = new Uint32Array(quadCount * 6);
    let ptr = 0;
    for (let r = 0; r < ny - 1; r++) {
      for (let c = 0; c < nx - 1; c++) {
        const i00 = r * nx + c;
        const i10 = i00 + 1;
        const i01 = (r + 1) * nx + c;
        const i11 = i01 + 1;
        indices[ptr++] = i00;
        indices[ptr++] = i10;
        indices[ptr++] = i11;
        indices[ptr++] = i00;
        indices[ptr++] = i11;
        indices[ptr++] = i01;
      }
    }
    this.indexCount = indices.length;
    this.indexBuffer = device.createBuffer({
      label: 'terrain-indices',
      size: indices.byteLength,
      usage: GPUBufferUsage.INDEX | GPUBufferUsage.COPY_DST,
    });
    device.queue.writeBuffer(this.indexBuffer, 0, indices);

    // Upload canopy point cloud
    this.canopyCount = n_canopy_pts;
    const canopyByteLen = Math.max(16, data.pack.canopyPts.byteLength);
    this.canopyBuffer = device.createBuffer({
      label: 'canopy-pts',
      size: canopyByteLen,
      usage: GPUBufferUsage.STORAGE | GPUBufferUsage.COPY_DST,
    });
    if (data.pack.canopyPts.byteLength > 0) {
      device.queue.writeBuffer(
        this.canopyBuffer,
        0,
        data.pack.canopyPts.buffer,
        data.pack.canopyPts.byteOffset,
        data.pack.canopyPts.byteLength
      );
    }

    // Upload aerial textures
    const keys: AerialLayerKey[] = ['ort_USA10', 'ort_old10', 'gazo1', 'seamlessphoto'];
    for (const key of keys) {
      const bmp = data.textures[key];
      if (bmp) {
        const tex = device.createTexture({
          label: `aerial-${key}`,
          size: [bmp.width, bmp.height, 1],
          format: 'rgba8unorm',
          usage:
            GPUTextureUsage.TEXTURE_BINDING |
            GPUTextureUsage.COPY_DST |
            GPUTextureUsage.RENDER_ATTACHMENT,
        });
        device.queue.copyExternalImageToTexture(
          { source: bmp },
          { texture: tex },
          [bmp.width, bmp.height]
        );
        this.aerialTextures[key] = tex;
        this.textureFlags[key] = true;
      } else {
        this.textureFlags[key] = false;
      }
    }

    const getView = (key: AerialLayerKey): GPUTextureView =>
      (this.aerialTextures[key] ?? this.gpu.placeholderTex).createView();

    this.terrainBindGroup = device.createBindGroup({
      layout: this.gpu.terrainBgl,
      entries: [
        { binding: 0, resource: { buffer: this.uniformBuffer } },
        { binding: 1, resource: { buffer: this.gridBuffer } },
        { binding: 2, resource: this.gpu.sampler },
        { binding: 3, resource: getView('ort_USA10') },
        { binding: 4, resource: getView('ort_old10') },
        { binding: 5, resource: getView('gazo1') },
        { binding: 6, resource: getView('seamlessphoto') },
      ],
    });

    this.canopyBindGroup = device.createBindGroup({
      layout: this.gpu.canopyBgl,
      entries: [
        { binding: 0, resource: { buffer: this.uniformBuffer } },
        { binding: 1, resource: { buffer: this.canopyBuffer } },
      ],
    });
  }

  public updateCaliperOverlay(caliper: CaliperResult | null, zExag: number): void {
    this.overlayVertexBuffer?.destroy();
    this.overlayVertexBuffer = null;
    this.overlayVertexCount = 0;

    if (!caliper || !this.loadedData || caliper.samples.length < 2) {
      return;
    }

    const { nx, ny, dx, z_min, z_max } = this.loadedData.pack.header;
    const halfW = (nx * dx) * 0.5;
    const halfH = (ny * dx) * 0.5;
    const zMid = 0.5 * (z_min + z_max);

    const samples = caliper.samples;
    const dX = caliper.p1.relX - caliper.p0.relX;
    const dY = caliper.p1.relY - caliper.p0.relY;
    const len = Math.max(1e-4, Math.hypot(dX, dY));
    // Perpendicular vector in XY plane for ribbon width
    const perpX = (-dY / len) * 0.45;
    const perpY = (dX / len) * 0.45;

    const segs = samples.length - 1;
    // Each ribbon segment: 6 verts; plus 2 endpoint diamond beacons (12 verts each = 24 verts)
    const totalVerts = segs * 6 + 24;
    const verts = new Float32Array(totalVerts * 4);
    let ptr = 0;

    const pushVert = (wx: number, wy: number, wz: number, kind: number) => {
      verts[ptr++] = wx;
      verts[ptr++] = wy;
      verts[ptr++] = wz;
      verts[ptr++] = kind;
    };

    for (let i = 0; i < segs; i++) {
      const a = samples[i];
      const b = samples[i + 1];
      const ax = a.relX - halfW;
      const ay = a.relY - halfH;
      const az = (a.zGnd - zMid) * zExag + 0.25;

      const bx = b.relX - halfW;
      const by = b.relY - halfH;
      const bz = (b.zGnd - zMid) * zExag + 0.25;

      pushVert(ax - perpX, ay - perpY, az, 0.0);
      pushVert(ax + perpX, ay + perpY, az, 0.0);
      pushVert(bx + perpX, by + perpY, bz, 0.0);

      pushVert(ax - perpX, ay - perpY, az, 0.0);
      pushVert(bx + perpX, by + perpY, bz, 0.0);
      pushVert(bx - perpX, by - perpY, bz, 0.0);
    }

    // Two endpoint beacons
    const endpoints = [caliper.p0, caliper.p1];
    const r = 1.1;
    const h = 3.2;
    for (const ep of endpoints) {
      const cx = ep.relX - halfW;
      const cy = ep.relY - halfH;
      const cz = (ep.zGnd - zMid) * zExag + 0.25;
      // Two crossed vertical quads
      pushVert(cx - r, cy, cz, 1.0);
      pushVert(cx + r, cy, cz, 1.0);
      pushVert(cx, cy, cz + h, 1.0);

      pushVert(cx, cy - r, cz, 1.0);
      pushVert(cx, cy + r, cz, 1.0);
      pushVert(cx, cy, cz + h, 1.0);

      pushVert(cx - r, cy - r, cz + 0.1, 1.0);
      pushVert(cx + r, cy - r, cz + 0.1, 1.0);
      pushVert(cx + r, cy + r, cz + 0.1, 1.0);

      pushVert(cx - r, cy - r, cz + 0.1, 1.0);
      pushVert(cx + r, cy + r, cz + 0.1, 1.0);
      pushVert(cx - r, cy + r, cz + 0.1, 1.0);
    }

    this.overlayVertexCount = totalVerts;
    this.overlayVertexBuffer = this.gpu.device.createBuffer({
      label: 'caliper-overlay-verts',
      size: verts.byteLength,
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST,
    });
    this.gpu.device.queue.writeBuffer(this.overlayVertexBuffer, 0, verts);
  }

  public render(camera: OrbitCamera, params: RenderParams): void {
    if (!this.loadedData || !this.terrainBindGroup || !this.indexBuffer) {
      return;
    }

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cssW = Math.max(1, this.canvas.clientWidth);
    const cssH = Math.max(1, this.canvas.clientHeight);
    const width = Math.min(4096, Math.max(1, Math.round(cssW * dpr)));
    const height = Math.min(4096, Math.max(1, Math.round(cssH * dpr)));

    if (this.canvas.width !== width || this.canvas.height !== height) {
      this.canvas.width = width;
      this.canvas.height = height;
    }

    if (!this.depthTex || this.depthW !== width || this.depthH !== height) {
      this.depthTex?.destroy();
      this.depthTex = this.gpu.device.createTexture({
        size: [width, height, 1],
        format: 'depth24plus',
        usage: GPUTextureUsage.RENDER_ATTACHMENT,
      });
      this.depthW = width;
      this.depthH = height;
    }

    const aspect = width / height;
    const { eye, viewProj } = camera.getViewProj(aspect);
    const { header, maxHag } = this.loadedData.pack;

    // Pack uniforms (176 bytes)
    this.uniformF32.set(viewProj, 0);
    this.uniformF32[16] = eye[0];
    this.uniformF32[17] = eye[1];
    this.uniformF32[18] = eye[2];
    this.uniformF32[19] = params.zExag;

    this.uniformF32[20] = header.dx;
    this.uniformF32[21] = header.z_min;
    this.uniformF32[22] = header.z_max;
    this.uniformF32[23] = maxHag;

    this.uniformU32[24] = header.nx;
    this.uniformU32[25] = header.ny;
    this.uniformU32[26] = layerIdToShaderIndex(params.primaryLayer);
    this.uniformU32[27] = layerIdToShaderIndex(params.compareLayer);

    this.uniformF32[28] = params.splitEnabled ? 1.0 : 0.0;
    this.uniformF32[29] = params.splitX;
    this.uniformF32[30] = (params.sunAzimuthDeg * Math.PI) / 180;
    this.uniformF32[31] = (params.sunElevationDeg * Math.PI) / 180;

    this.uniformF32[32] = width;
    this.uniformF32[33] = height;
    this.uniformF32[34] = params.peel;
    this.uniformF32[35] = params.pointSizePx;

    this.uniformF32[36] = params.showGridOverlay ? 1.0 : 0.0;
    this.uniformF32[37] = this.textureFlags.ort_USA10 ? 1.0 : 0.0;
    this.uniformF32[38] = this.textureFlags.ort_old10 ? 1.0 : 0.0;
    this.uniformF32[39] = this.textureFlags.gazo1 ? 1.0 : 0.0;

    this.uniformF32[40] = this.textureFlags.seamlessphoto ? 1.0 : 0.0;
    this.uniformF32[41] = dpr;
    this.uniformF32[42] = 0;
    this.uniformF32[43] = 0;

    this.gpu.device.queue.writeBuffer(this.uniformBuffer, 0, this.uniformData);
    this.gpu.device.queue.writeBuffer(
      this.overlayUniformBuffer,
      0,
      viewProj.buffer as ArrayBuffer,
      viewProj.byteOffset,
      viewProj.byteLength
    );

    const colorView = this.context.getCurrentTexture().createView();
    const encoder = this.gpu.device.createCommandEncoder();
    const pass = encoder.beginRenderPass({
      colorAttachments: [
        {
          view: colorView,
          clearValue: { r: 0.043, g: 0.055, b: 0.078, a: 1.0 },
          loadOp: 'clear',
          storeOp: 'store',
        },
      ],
      depthStencilAttachment: {
        view: this.depthTex.createView(),
        depthClearValue: 1.0,
        depthLoadOp: 'clear',
        depthStoreOp: 'store',
      },
    });

    // 1. Bare-Earth 0.5m Displacement Mesh
    pass.setPipeline(this.gpu.terrainPipeline);
    pass.setBindGroup(0, this.terrainBindGroup);
    pass.setIndexBuffer(this.indexBuffer, 'uint32');
    pass.drawIndexed(this.indexCount);

    // 2. Subsampled 3D Canopy Point Cloud ("Peel the Forest")
    if (params.peel > 0.001 && this.canopyCount > 0 && this.canopyBindGroup) {
      pass.setPipeline(this.gpu.canopyPipeline);
      pass.setBindGroup(0, this.canopyBindGroup);
      pass.draw(6, this.canopyCount);
    }

    // 3. 3D Caliper Transect & Endpoint Beacons
    if (this.overlayVertexCount > 0 && this.overlayVertexBuffer) {
      pass.setPipeline(this.gpu.overlayPipeline);
      pass.setBindGroup(0, this.overlayBindGroup);
      pass.setVertexBuffer(0, this.overlayVertexBuffer);
      pass.draw(this.overlayVertexCount);
    }

    pass.end();
    this.gpu.device.queue.submit([encoder.finish()]);
  }

  public dispose(): void {
    this.uniformBuffer.destroy();
    this.overlayUniformBuffer.destroy();
    this.depthTex?.destroy();
    this.gridBuffer?.destroy();
    this.indexBuffer?.destroy();
    this.canopyBuffer?.destroy();
    this.overlayVertexBuffer?.destroy();
    for (const tex of Object.values(this.aerialTextures)) {
      tex?.destroy();
    }
  }
}
