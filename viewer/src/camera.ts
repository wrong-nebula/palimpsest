import { invertMat4, lookAt, mulMat4, normalize3, perspectiveZO, sub3, transformPoint4, type Vec3 } from './math';

export class OrbitCamera {
  public yaw = -Math.PI * 0.35;     // azimuth in XY plane (CCW from +East)
  public pitch = 0.68;              // elevation above horizon (rad)
  public distance = 250.0;          // meters
  public target: Vec3 = [0, 0, 0];
  public fovY = (45 * Math.PI) / 180;
  public near = 0.5;
  public far = 4000.0;

  public reset(): void {
    this.yaw = -Math.PI * 0.35;
    this.pitch = 0.68;
    this.distance = 250.0;
    this.target = [0, 0, 0];
  }

  public setTopDown(): void {
    this.yaw = -Math.PI * 0.5; // North up
    this.pitch = 1.48;
    this.distance = 270.0;
    this.target = [0, 0, 0];
  }

  public orbit(deltaX: number, deltaY: number): void {
    this.yaw -= deltaX * 0.0065;
    this.pitch = Math.max(0.08, Math.min(1.52, this.pitch + deltaY * 0.0065));
  }

  public pan(deltaX: number, deltaY: number): void {
    const panSpeed = this.distance * 0.0014;
    // Right vector in XY plane perpendicular to camera look direction
    const cosY = Math.cos(this.yaw);
    const sinY = Math.sin(this.yaw);
    // Forward in XY from eye to target is (-cosY, -sinY)
    // Right is (-sinY, cosY) -> wait: forward x up(+Z) = (-cosY, -sinY, 0) x (0,0,1) = (-sinY, cosY, 0)
    const rx = -sinY;
    const ry = cosY;
    // Camera up projected onto XY/Z
    const fx = -cosY * Math.sin(this.pitch);
    const fy = -sinY * Math.sin(this.pitch);
    const fz = Math.cos(this.pitch);

    this.target = [
      this.target[0] - rx * deltaX * panSpeed + fx * deltaY * panSpeed,
      this.target[1] - ry * deltaX * panSpeed + fy * deltaY * panSpeed,
      this.target[2] + fz * deltaY * panSpeed * 0.5,
    ];
  }

  public zoom(deltaY: number): void {
    const factor = Math.exp(deltaY * 0.0011);
    this.distance = Math.max(25.0, Math.min(900.0, this.distance * factor));
  }

  public getEye(): Vec3 {
    const cp = Math.cos(this.pitch);
    const sp = Math.sin(this.pitch);
    const cy = Math.cos(this.yaw);
    const sy = Math.sin(this.yaw);
    return [
      this.target[0] + this.distance * cp * cy,
      this.target[1] + this.distance * cp * sy,
      this.target[2] + this.distance * sp,
    ];
  }

  public getViewProj(aspect: number): {
    eye: Vec3;
    view: Float32Array;
    proj: Float32Array;
    viewProj: Float32Array;
  } {
    const eye = this.getEye();
    const view = lookAt(eye, this.target, [0, 0, 1]);
    const proj = perspectiveZO(this.fovY, aspect, this.near, this.far);
    const viewProj = mulMat4(proj, view);
    return { eye, view, proj, viewProj };
  }

  public screenToRay(
    normX: number, // 0..1 left-to-right
    normY: number, // 0..1 top-to-bottom
    aspect: number
  ): { origin: Vec3; dir: Vec3 } | null {
    const { viewProj } = this.getViewProj(aspect);
    const inv = invertMat4(viewProj);
    if (!inv) return null;

    const ndcX = normX * 2.0 - 1.0;
    const ndcY = 1.0 - normY * 2.0;

    const pNear = transformPoint4(inv, [ndcX, ndcY, 0.0, 1.0]);
    const pFar = transformPoint4(inv, [ndcX, ndcY, 1.0, 1.0]);
    const dir = normalize3(sub3(pFar, pNear));
    return { origin: pNear, dir };
  }
}
