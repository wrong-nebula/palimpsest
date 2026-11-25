(function(){const e=document.createElement("link").relList;if(e&&e.supports&&e.supports("modulepreload"))return;for(const a of document.querySelectorAll('link[rel="modulepreload"]'))r(a);new MutationObserver(a=>{for(const l of a)if(l.type==="childList")for(const s of l.addedNodes)s.tagName==="LINK"&&s.rel==="modulepreload"&&r(s)}).observe(document,{childList:!0,subtree:!0});function n(a){const l={};return a.integrity&&(l.integrity=a.integrity),a.referrerPolicy&&(l.referrerPolicy=a.referrerPolicy),a.crossOrigin==="use-credentials"?l.credentials="include":a.crossOrigin==="anonymous"?l.credentials="omit":l.credentials="same-origin",l}function r(a){if(a.ep)return;a.ep=!0;const l=n(a);fetch(a.href,l)}})();function dt(t,e){return[t[0]-e[0],t[1]-e[1],t[2]-e[2]]}function Se(t,e){return t[0]*e[0]+t[1]*e[1]+t[2]*e[2]}function tt(t,e){return[t[1]*e[2]-t[2]*e[1],t[2]*e[0]-t[0]*e[2],t[0]*e[1]-t[1]*e[0]]}function Le(t){const e=Math.hypot(t[0],t[1],t[2]);return e<1e-12?[0,0,1]:[t[0]/e,t[1]/e,t[2]/e]}function Lt(t,e,n,r){const a=1/Math.tan(t*.5),l=1/(n-r),s=new Float32Array(16);return s[0]=a/Math.max(e,1e-4),s[5]=a,s[10]=r*l,s[11]=-1,s[14]=r*n*l,s}function Pt(t,e,n){const r=Le(dt(t,e)),a=Le(tt(n,r)),l=tt(r,a),s=new Float32Array(16);return s[0]=a[0],s[1]=l[0],s[2]=r[0],s[3]=0,s[4]=a[1],s[5]=l[1],s[6]=r[1],s[7]=0,s[8]=a[2],s[9]=l[2],s[10]=r[2],s[11]=0,s[12]=-Se(a,t),s[13]=-Se(l,t),s[14]=-Se(r,t),s[15]=1,s}function It(t,e){const n=new Float32Array(16);for(let r=0;r<4;r++){const a=e[r*4+0],l=e[r*4+1],s=e[r*4+2],o=e[r*4+3];n[r*4+0]=t[0]*a+t[4]*l+t[8]*s+t[12]*o,n[r*4+1]=t[1]*a+t[5]*l+t[9]*s+t[13]*o,n[r*4+2]=t[2]*a+t[6]*l+t[10]*s+t[14]*o,n[r*4+3]=t[3]*a+t[7]*l+t[11]*s+t[15]*o}return n}function Gt(t){const e=t[0],n=t[1],r=t[2],a=t[3],l=t[4],s=t[5],o=t[6],d=t[7],v=t[8],p=t[9],z=t[10],w=t[11],h=t[12],y=t[13],m=t[14],S=t[15],E=e*s-n*l,L=e*o-r*l,P=e*d-a*l,A=n*o-r*s,B=n*d-a*s,F=r*d-a*o,x=v*y-p*h,u=v*m-z*h,_=v*S-w*h,g=p*m-z*y,M=p*S-w*y,C=z*S-w*m;let I=E*C-L*M+P*g+A*_-B*u+F*x;if(Math.abs(I)<1e-12)return null;I=1/I;const G=new Float32Array(16);return G[0]=(s*C-o*M+d*g)*I,G[1]=(r*M-n*C-a*g)*I,G[2]=(y*F-m*B+S*A)*I,G[3]=(z*B-p*F-w*A)*I,G[4]=(o*_-l*C-d*u)*I,G[5]=(e*C-r*_+a*u)*I,G[6]=(m*P-h*F-S*L)*I,G[7]=(v*F-z*P+w*L)*I,G[8]=(l*M-s*_+d*x)*I,G[9]=(n*_-e*M-a*x)*I,G[10]=(h*B-y*P+S*E)*I,G[11]=(p*P-v*B-w*E)*I,G[12]=(s*u-l*g-o*x)*I,G[13]=(e*g-n*u+r*x)*I,G[14]=(y*L-h*A-m*E)*I,G[15]=(v*A-p*L+z*E)*I,G}function nt(t,e){const n=t[0]*e[0]+t[4]*e[1]+t[8]*e[2]+t[12]*e[3],r=t[1]*e[0]+t[5]*e[1]+t[9]*e[2]+t[13]*e[3],a=t[2]*e[0]+t[6]*e[1]+t[10]*e[2]+t[14]*e[3],l=t[3]*e[0]+t[7]*e[1]+t[11]*e[2]+t[15]*e[3],s=Math.abs(l)>1e-12?1/l:1;return[n*s,r*s,a*s]}class Tt{yaw=-Math.PI*.35;pitch=.68;distance=250;target=[0,0,0];fovY=45*Math.PI/180;near=.5;far=4e3;reset(){this.yaw=-Math.PI*.35,this.pitch=.68,this.distance=250,this.target=[0,0,0]}setTopDown(){this.yaw=-Math.PI*.5,this.pitch=1.48,this.distance=270,this.target=[0,0,0]}orbit(e,n){this.yaw-=e*.0065,this.pitch=Math.max(.08,Math.min(1.52,this.pitch+n*.0065))}pan(e,n){const r=this.distance*.0014,a=Math.cos(this.yaw),l=Math.sin(this.yaw),s=-l,o=a,d=-a*Math.sin(this.pitch),v=-l*Math.sin(this.pitch),p=Math.cos(this.pitch);this.target=[this.target[0]-s*e*r+d*n*r,this.target[1]-o*e*r+v*n*r,this.target[2]+p*n*r*.5]}zoom(e){const n=Math.exp(e*.0011);this.distance=Math.max(25,Math.min(900,this.distance*n))}getEye(){const e=Math.cos(this.pitch),n=Math.sin(this.pitch),r=Math.cos(this.yaw),a=Math.sin(this.yaw);return[this.target[0]+this.distance*e*r,this.target[1]+this.distance*e*a,this.target[2]+this.distance*n]}getViewProj(e){const n=this.getEye(),r=Pt(n,this.target,[0,0,1]),a=Lt(this.fovY,e,this.near,this.far),l=It(a,r);return{eye:n,view:r,proj:a,viewProj:l}}screenToRay(e,n,r){const{viewProj:a}=this.getViewProj(r),l=Gt(a);if(!l)return null;const s=e*2-1,o=1-n*2,d=nt(l,[s,o,0,1]),v=nt(l,[s,o,1,1]),p=Le(dt(v,d));return{origin:d,dir:p}}}function he(t,e,n,r,a,l){const s=Math.max(0,Math.min(e-1.001,a/r-.5)),o=Math.max(0,Math.min(n-1.001,l/r-.5)),d=Math.floor(s),v=Math.floor(o),p=Math.min(e-1,d+1),z=Math.min(n-1,v+1),w=s-d,h=o-v,y=t[v*e+d],m=t[v*e+p],S=t[z*e+d],E=t[z*e+p],L=y*(1-w)+m*w,P=S*(1-w)+E*w;return L*(1-h)+P*h}function rt(t,e,n,r){const{nx:a,ny:l,dx:s,z_min:o,z_max:d}=t.header,v=a*s,p=l*s,z=v*.5,w=p*.5,h=.5*(o+d),y=t.layers.z_gnd,m=[-z,-w,(o-h)*e-2],S=[z,w,(d-h)*e+2];let E=.5,L=2e3;for(let x=0;x<3;x++){const u=n[x],_=r[x];if(Math.abs(_)<1e-8){if(u<m[x]||u>S[x])return null}else{let g=(m[x]-u)/_,M=(S[x]-u)/_;if(g>M){const C=g;g=M,M=C}if(E=Math.max(E,g),L=Math.min(L,M),E>L)return null}}const P=x=>{const u=n[0]+r[0]*x,_=n[1]+r[1]*x,g=n[2]+r[2]*x,M=Math.max(0,Math.min(v,u+z)),C=Math.max(0,Math.min(p,_+w)),I=he(y,a,l,s,M,C),G=(I-h)*e;return{diff:g-G,relX:M,relY:C,zGnd:I}},A=.5;let B=E,F=P(B);if(F.diff<=0)return{relX:F.relX,relY:F.relY,zGnd:F.zGnd};for(let x=E+A;x<=L;x+=A){const u=P(x);if(u.diff<=0){let _=B,g=x;for(let C=0;C<12;C++){const I=.5*(_+g);P(I).diff>0?_=I:g=I}const M=P(.5*(_+g));return{relX:M.relX,relY:M.relY,zGnd:M.zGnd}}B=x,F=u}return null}function ot(t,e,n,r=180){const{nx:a,ny:l,dx:s}=t.header,{z_gnd:o,rho_gnd:d,lrm:v}=t.layers,p=n.relX-e.relX,z=n.relY-e.relY,w=Math.hypot(p,z),h=[];let y=1/0,m=-1/0,S=1/0,E=-1/0,L=1/0,P=0;const A=Math.max(2,r);for(let u=0;u<A;u++){const _=u/(A-1),g=e.relX+p*_,M=e.relY+z*_,C=w*_,I=he(o,a,l,s,g,M),G=he(d,a,l,s,g,M),V=he(v,a,l,s,g,M);h.push({s:C,relX:g,relY:M,zGnd:I,rhoGnd:G,lrm:V}),I<y&&(y=I),I>m&&(m=I),V<S&&(S=V),V>E&&(E=V),G<L&&(L=G),P+=G}let B=0;const F=w/Math.max(1,A-1),x=Math.max(1,Math.round(1/Math.max(F,.05)));if(w>.1)for(let u=x;u<h.length;u++){const _=h[u-x],g=h[u],M=Math.max(1e-4,g.s-_.s),C=Math.atan(Math.abs(g.zGnd-_.zGnd)/M)*180/Math.PI;C>B&&(B=C)}return{p0:e,p1:n,lengthM:w,samples:h,wallHeightM:Math.max(0,m-y),scarpSlopeDeg:B,localReliefM:Math.max(0,E-S),lrmMinM:S,lrmMaxM:E,minRhoGnd:L,meanRhoGnd:P/h.length}}function Ce(t,e){const n=Math.min(window.devicePixelRatio||1,2),r=t.clientWidth||260,a=t.clientHeight||132,l=Math.round(r*n),s=Math.round(a*n);(t.width!==l||t.height!==s)&&(t.width=l,t.height=s);const o=t.getContext("2d");if(!o)return;if(o.save(),o.scale(n,n),o.fillStyle="#0c1017",o.fillRect(0,0,r,a),!e||e.samples.length<2||e.lengthM<.2){o.strokeStyle="#1f2937",o.strokeRect(.5,.5,r-1,a-1),o.fillStyle="#7f8ea3",o.font="10px ui-monospace, SFMono-Regular, Menlo, monospace",o.textAlign="center",o.fillText("Caliper or Shift+Drag on terrain",r*.5,a*.5-4),o.fillStyle="#536278",o.fillText("to slice z_gnd + rho_gnd",r*.5,a*.5+12),o.restore();return}const d=32,v=30,p=14,z=20,w=Math.max(10,r-d-v),h=Math.max(10,a-p-z),y=e.samples;let m=1/0,S=-1/0,E=1;for(const u of y)u.zGnd<m&&(m=u.zGnd),u.zGnd>S&&(S=u.zGnd),u.rhoGnd>E&&(E=u.rhoGnd);const L=Math.max(.5,S-m);m-=L*.08,S+=L*.08,E=Math.max(2,Math.ceil(E*1.15));const P=u=>d+u/e.lengthM*w,A=u=>p+h-(u-m)/(S-m)*h,B=u=>p+h-Math.min(u,E)/E*h;o.strokeStyle="#1c2533",o.lineWidth=1;for(let u=0;u<=3;u++){const _=p+h*u/3;o.beginPath(),o.moveTo(d,_),o.lineTo(d+w,_),o.stroke()}o.fillStyle="rgba(230, 57, 70, 0.22)";for(let u=0;u<y.length-1;u++)if(y[u].rhoGnd<.5||y[u+1].rhoGnd<.5){const _=P(y[u].s),g=P(y[u+1].s);o.fillRect(_,p,Math.max(1,g-_),h)}const F=B(.5);o.save(),o.strokeStyle="#ff4d5a",o.setLineDash([4,3]),o.lineWidth=1,o.beginPath(),o.moveTo(d,F),o.lineTo(d+w,F),o.stroke(),o.restore(),o.beginPath(),o.moveTo(P(y[0].s),p+h);for(const u of y)o.lineTo(P(u.s),A(u.zGnd));o.lineTo(P(y[y.length-1].s),p+h),o.closePath();const x=o.createLinearGradient(0,p,0,p+h);x.addColorStop(0,"rgba(56, 189, 248, 0.34)"),x.addColorStop(1,"rgba(56, 189, 248, 0.03)"),o.fillStyle=x,o.fill(),o.strokeStyle="#38bdf8",o.lineWidth=1.8,o.beginPath(),y.forEach((u,_)=>{const g=P(u.s),M=A(u.zGnd);_===0?o.moveTo(g,M):o.lineTo(g,M)}),o.stroke(),o.lineWidth=1.4;for(let u=0;u<y.length-1;u++){const _=y[u],g=y[u+1];o.strokeStyle=_.rhoGnd<.5||g.rhoGnd<.5?"#ff4d5a":"#34d399",o.beginPath(),o.moveTo(P(_.s),B(_.rhoGnd)),o.lineTo(P(g.s),B(g.rhoGnd)),o.stroke()}o.fillStyle="#93c5fd",o.font="10px ui-monospace, SFMono-Regular, Menlo, monospace",o.textAlign="right",o.fillText(S.toFixed(1),d-3,p+7),o.fillText(m.toFixed(1),d-3,p+h),o.fillStyle="#6ee7b7",o.textAlign="left",o.fillText(`${E.toFixed(0)}/m²`,d+w+3,p+7),o.fillStyle="#ff6b78",o.fillText("0.5",d+w+3,Math.min(p+h,Math.max(p+14,F+3))),o.fillStyle="#94a3b8",o.textAlign="center",o.fillText("0m",d,a-5),o.fillText(`${e.lengthM.toFixed(1)}m`,d+w-10,a-5),o.fillStyle="#cbd5e1",o.fillText("z_gnd (m) & rho_gnd (/m²)",d+w*.5,10),o.restore()}function ee(t){return t.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&apos;")}function At(t){switch(t){case"Class A":return"Flag, Red";case"Class B":return"Flag, Blue";case"Class C":return"Flag, Green";default:return"Flag, Black"}}function Ft(t,e,n){const r=new Date().toISOString(),a=['<?xml version="1.0" encoding="UTF-8"?>','<gpx version="1.1" creator="PALIMPSEST Seeing Space Bench" xmlns="http://www.topografix.com/GPX/1/1">',"  <metadata>",`    <name>${ee(`PALIMPSEST Filtered Waypoints — ${e}`)}</name>`,`    <time>${ee(r)}</time>`,"  </metadata>"];for(const l of t){const s=n?.get(l.candidate_id)??0,o=`[${l.temporal_class}] ${l.morphology} | wall=${l.wall_height_m.toFixed(1)}m scarp=${l.scarp_slope_deg.toFixed(1)}° rho=${l.mean_rho_gnd.toFixed(2)}/m2`,d=At(l.temporal_class);a.push(`  <wpt lat="${l.lat.toFixed(7)}" lon="${l.lon.toFixed(7)}">`),a.push(`    <ele>${s.toFixed(2)}</ele>`),a.push(`    <name>${ee(l.candidate_id)}</name>`),a.push(`    <cmt>${ee(o)}</cmt>`),a.push(`    <sym>${ee(d)}</sym>`),a.push(`    <type>${ee(l.temporal_class)}</type>`),a.push("  </wpt>")}return a.push("</gpx>"),a.join(`
`)+`
`}function Ut(t,e="palimpsest_filtered.gpx"){const n=new Blob([t],{type:"application/gpx+xml;charset=utf-8"}),r=URL.createObjectURL(n),a=document.createElement("a");a.href=r,a.download=e,document.body.appendChild(a),a.click(),document.body.removeChild(a),setTimeout(()=>URL.revokeObjectURL(r),1e3)}const ut="./data",ue=64,at=10;function pe(t){const e=t.replace(/^\.?\//,"");return`${ut}/${e}`}async function Rt(){const t=`${ut}/candidates.json`,e=await fetch(t,{cache:"no-store"});if(!e.ok)throw new Error(`Failed to fetch ${t}: HTTP ${e.status} ${e.statusText}`);const n=await e.json();if(!n||!Array.isArray(n.candidates))throw new Error("Invalid candidates.json schema: missing candidates array");if(n.funnel.after_raw_ground_confirmation!==void 0){const r=await fetch(pe("field_support.json"),{cache:"no-store"});if(!r.ok)throw new Error("Ground-support catalog is missing");n.fieldSupport=await r.json();for(const a of n.candidates){const l=n.fieldSupport.candidates[a.candidate_id];if(!l||l.x_6676!==a.x_6676||l.y_6676!==a.y_6676)throw new Error("Ground-support catalog is out of date")}}return n}function kt(t){if(t.byteLength<ue)throw new Error(`PLMP pack too small: ${t.byteLength} bytes`);const e=new Uint8Array(t),n=String.fromCharCode(e[0],e[1],e[2],e[3]);if(n!=="PLMP")throw new Error(`Invalid PLMP magic: "${n}"`);const r=new DataView(t),a=r.getUint32(4,!0);if(a!==1)throw new Error(`Unsupported PLMP version: ${a}`);const l=r.getUint32(8,!0),s=r.getUint32(12,!0),o=r.getFloat64(16,!0),d=r.getFloat64(24,!0),v=r.getFloat32(32,!0),p=r.getUint32(36,!0),z=r.getUint32(40,!0),w=r.getFloat32(44,!0),h=r.getFloat32(48,!0);if(p!==at)throw new Error(`Expected ${at} planar layers, got ${p}`);const y=l*s,m=p*y*4,S=z*4*4,E=ue+m+S;if(t.byteLength<E)throw new Error(`Truncated PLMP pack: got ${t.byteLength} bytes, expected >= ${E}`);const L={magic:n,version:a,nx:l,ny:s,x0:o,y0:d,dx:v,n_layers:p,n_canopy_pts:z,z_min:w,z_max:h},P=new Float32Array(t,ue,p*y),A=u=>P.subarray(u*y,(u+1)*y),B=ue+m,F=new Float32Array(t,B,z*4);let x=1;for(let u=3;u<F.length;u+=4){const _=F[u];Number.isFinite(_)&&_>x&&(x=_)}return{header:L,rawGridBuffer:P,layers:{z_gnd:A(0),chm:A(1),rho_gnd:A(2),rrim_r:A(3),rrim_g:A(4),rrim_b:A(5),svf:A(6),lrm:A(7),openness_diff:A(8),flow_violation:A(9)},canopyPts:F,maxHag:x}}async function $t(t){const e=pe(t),n=await fetch(e);if(!n.ok)throw new Error(`Failed to fetch pack ${e}: HTTP ${n.status}`);const r=await n.arrayBuffer();return kt(r)}async function Dt(t){if(!t)return null;const e=pe(t);try{const n=await fetch(e);if(!n.ok)return null;const r=await n.blob();return await createImageBitmap(r)}catch{return null}}async function Ot(t){const e=["ort_USA10","ort_old10","gazo1","seamlessphoto"],n=await Promise.all(e.map(async r=>{const a=t.textures?.[r]??null,l=await Dt(a);return[r,l]}));return{ort_USA10:n[0][1],ort_old10:n[1][1],gazo1:n[2][1],seamlessphoto:n[3][1]}}let fe;async function Vt(t,e){const{nx:n,ny:r,x0:a,y0:l,dx:s}=t.header,o=new Float32Array(n*r);if(!e)return o.fill(-1);fe||(fe=(async()=>{const E=await fetch(pe("ground_coverage.u8.gz"),{cache:"no-store"});if(!E.ok||!E.body)throw new Error("Ground coverage raster is missing");const L=new Uint8Array(await E.arrayBuffer());if(L[0]!==31||L[1]!==139)return L;const P=new Blob([L]).stream().pipeThrough(new DecompressionStream("gzip"));return new Uint8Array(await new Response(P).arrayBuffer())})().catch(E=>{throw fe=void 0,E}));const d=await fe,[v,p,z,w]=e.bounds,h=Math.round((z-v)/e.dx),y=Math.round((w-p)/e.dx),m=Math.round((a-v)/s),S=Math.round((l-p)/s);if(d.length!==h*y||s!==e.dx||m<0||S<0||m+n>h||S+r>y)throw new Error("Coverage and terrain grids do not align");for(let E=0;E<r;E++){const L=(S+E)*h+m;o.set(d.subarray(L,L+n),E*n)}return o}async function Nt(t,e){if(!t.pack_file)throw new Error(`Candidate ${t.candidate_id} has no pack_file`);const[n,r]=await Promise.all([$t(t.pack_file),Ot(t)]),a=!!(t.textures?.ort_USA10&&r.ort_USA10);return{candidate:t,pack:n,textures:r,ortUsa10Available:a,coverage:await Vt(n,e)}}const ft="palimpsest.annotations.v1";function Xt(){try{const t=window.localStorage.getItem(ft);if(!t)return{};const e=JSON.parse(t),n={};for(const[r,a]of Object.entries(e))(a==="Confirmed"||a==="Natural"||a==="Modern")&&(n[r]=a);return n}catch{return{}}}function jt(t){try{window.localStorage.setItem(ft,JSON.stringify(t))}catch{}}function it(t,e){return e==="All"?t:t.filter(n=>n.temporal_class===e)}function Yt(t){return t.filter(e=>e.status==="rejected")}const te=[{id:"rrim",label:"Chiba RRIM",shortLabel:"RRIM",shaderIndex:0,isAerial:!1},{id:"raking_sun",label:"Live Raking-Light Sun",shortLabel:"Sun",shaderIndex:1,isAerial:!1},{id:"svf",label:"Zaksek SVF",shortLabel:"SVF",shaderIndex:2,isAerial:!1},{id:"lrm",label:"Hesse LRM",shortLabel:"LRM",shaderIndex:3,isAerial:!1},{id:"flow_violation",label:"Drainage Violation",shortLabel:"Flow",shaderIndex:4,isAerial:!1},{id:"rho_gnd",label:"Ground Confidence (rho_gnd)",shortLabel:"rho_gnd",shaderIndex:5,isAerial:!1},{id:"coverage",label:"Survey coverage by density band",shortLabel:"Coverage",shaderIndex:10,isAerial:!1},{id:"ort_USA10",label:"GSI 1945 (ort_USA10)",shortLabel:"1945",shaderIndex:6,isAerial:!0,aerialKey:"ort_USA10"},{id:"ort_old10",label:"GSI 1965 (ort_old10)",shortLabel:"1965",shaderIndex:7,isAerial:!0,aerialKey:"ort_old10"},{id:"gazo1",label:"GSI 1975 (gazo1)",shortLabel:"1975",shaderIndex:8,isAerial:!0,aerialKey:"gazo1"},{id:"seamlessphoto",label:"GSI Today (seamlessphoto)",shortLabel:"Today",shaderIndex:9,isAerial:!0,aerialKey:"seamlessphoto"}],Wt=`struct Uniforms {
  view_proj: mat4x4<f32>,   // offset 0
  cam_eye: vec4<f32>,       // xyz = eye, w = z_exag
  grid_info: vec4<f32>,     // x = dx, y = z_min, z = z_max, w = max_hag
  grid_dims: vec4<u32>,     // x = nx, y = ny, z = primary_layer, w = compare_layer
  wipe_sun: vec4<f32>,      // x = split_enabled, y = split_x, z = sun_az_rad, w = sun_el_rad
  viewport: vec4<f32>,      // x = width_px, y = height_px, z = peel, w = point_size_m
  flags: vec4<f32>,         // x = show_grid, y = has_usa10, z = has_old10, w = has_gazo1
  flags2: vec4<f32>,        // x = has_seamless, y = dpr, z = 0.0, w = 0.0
};

@group(0) @binding(0) var<uniform> u: Uniforms;
@group(0) @binding(1) var<storage, read> grid_data: array<f32>;
@group(0) @binding(2) var aerial_sampler: sampler;
@group(0) @binding(3) var tex_usa10: texture_2d<f32>;
@group(0) @binding(4) var tex_old10: texture_2d<f32>;
@group(0) @binding(5) var tex_gazo1: texture_2d<f32>;
@group(0) @binding(6) var tex_seamless: texture_2d<f32>;

struct VsOut {
  @builtin(position) clip_pos: vec4<f32>,
  @location(0) uv: vec2<f32>,
  @location(1) grid_coord: vec2<f32>,
  @location(2) world_pos: vec3<f32>,
};

fn read_cell(layer_idx: u32, col: i32, row: i32) -> f32 {
  let nx = i32(u.grid_dims.x);
  let ny = i32(u.grid_dims.y);
  let c = clamp(col, 0, nx - 1);
  let r = clamp(row, 0, ny - 1);
  let stride = u32(nx * ny);
  return grid_data[layer_idx * stride + u32(r * nx + c)];
}

fn sample_bilinear(layer_idx: u32, gx: f32, gy: f32) -> f32 {
  let nx = f32(u.grid_dims.x);
  let ny = f32(u.grid_dims.y);
  let cx = clamp(gx, 0.0, nx - 1.001);
  let cy = clamp(gy, 0.0, ny - 1.001);
  let c0 = i32(floor(cx));
  let r0 = i32(floor(cy));
  let c1 = min(i32(u.grid_dims.x) - 1, c0 + 1);
  let r1 = min(i32(u.grid_dims.y) - 1, r0 + 1);
  let fx = cx - f32(c0);
  let fy = cy - f32(r0);

  let v00 = read_cell(layer_idx, c0, r0);
  let v10 = read_cell(layer_idx, c1, r0);
  let v01 = read_cell(layer_idx, c0, r1);
  let v11 = read_cell(layer_idx, c1, r1);
  return mix(mix(v00, v10, fx), mix(v01, v11, fx), fy);
}

fn compute_normal_metric(gx: f32, gy: f32) -> vec3<f32> {
  let dx = u.grid_info.x;
  let z_l = sample_bilinear(0u, gx - 1.0, gy);
  let z_r = sample_bilinear(0u, gx + 1.0, gy);
  let z_d = sample_bilinear(0u, gx, gy - 1.0);
  let z_u = sample_bilinear(0u, gx, gy + 1.0);
  let dzdx = (z_r - z_l) / (2.0 * dx);
  let dzdy = (z_u - z_d) / (2.0 * dx);
  return normalize(vec3<f32>(-dzdx, -dzdy, 1.0));
}

@vertex
fn vs_main(@builtin(vertex_index) vid: u32) -> VsOut {
  let nx = u.grid_dims.x;
  let ny = u.grid_dims.y;
  let col = vid % nx;
  let row = vid / nx;

  let dx = u.grid_info.x;
  let width_m = f32(nx) * dx;
  let height_m = f32(ny) * dx;

  let rel_x = (f32(col) + 0.5) * dx;
  let rel_y = (f32(row) + 0.5) * dx;

  let z = read_cell(0u, i32(col), i32(row));
  let z_mid = 0.5 * (u.grid_info.y + u.grid_info.z);

  let wx = rel_x - width_m * 0.5;
  let wy = rel_y - height_m * 0.5;
  let wz = (z - z_mid) * u.cam_eye.w;

  var out: VsOut;
  out.world_pos = vec3<f32>(wx, wy, wz);
  out.clip_pos = u.view_proj * vec4<f32>(wx, wy, wz, 1.0);
  // CONTRACT.md §2.3: u = rel_x / width_m, v = 1.0 - rel_y / height_m (v=0 is North)
  out.uv = vec2<f32>(rel_x / width_m, 1.0 - rel_y / height_m);
  out.grid_coord = vec2<f32>(f32(col), f32(row));
  return out;
}

fn color_svf(svf: f32) -> vec3<f32> {
  let t = clamp(svf, 0.0, 1.0);
  let c0 = vec3<f32>(0.04, 0.07, 0.14);
  let c1 = vec3<f32>(0.24, 0.34, 0.45);
  let c2 = vec3<f32>(0.93, 0.96, 0.99);
  if (t < 0.5) {
    return mix(c0, c1, t * 2.0);
  }
  return mix(c1, c2, (t - 0.5) * 2.0);
}

fn color_lrm(lrm: f32) -> vec3<f32> {
  // Diverging palette around 0m: [-2.0m .. 0 .. +2.0m]
  let t = clamp(lrm / 1.8, -1.0, 1.0);
  let neg = vec3<f32>(0.11, 0.42, 0.85);
  let mid = vec3<f32>(0.18, 0.21, 0.27);
  let pos = vec3<f32>(0.95, 0.46, 0.16);
  let pos_hi = vec3<f32>(1.0, 0.84, 0.42);
  if (t < 0.0) {
    return mix(mid, neg, -t);
  }
  if (t < 0.6) {
    return mix(mid, pos, t / 0.6);
  }
  return mix(pos, pos_hi, (t - 0.6) / 0.4);
}

fn color_flow_violation(v: f32) -> vec3<f32> {
  let t = clamp(v, 0.0, 1.0);
  let c0 = vec3<f32>(0.07, 0.09, 0.15);
  let c1 = vec3<f32>(0.48, 0.17, 0.72);
  let c2 = vec3<f32>(0.96, 0.49, 0.04);
  let c3 = vec3<f32>(1.0, 0.95, 0.65);
  if (t < 0.35) {
    return mix(c0, c1, t / 0.35);
  }
  if (t < 0.72) {
    return mix(c1, c2, (t - 0.35) / 0.37);
  }
  return mix(c2, c3, (t - 0.72) / 0.28);
}

fn color_rho_gnd(rho: f32, gx: f32, gy: f32) -> vec3<f32> {
  // Anti-hallucination provenance gate: red warning below 0.5 pts/m2
  if (rho < 0.5) {
    let stripe = step(0.5, fract((gx + gy) * 0.25));
    let severity = 1.0 - clamp(rho / 0.5, 0.0, 1.0);
    let red_lo = vec3<f32>(0.78, 0.10, 0.16);
    let red_hi = vec3<f32>(0.98, 0.22, 0.26);
    return mix(red_lo, red_hi, 0.45 * severity + 0.35 * stripe);
  }
  let t = clamp((rho - 0.5) / 3.5, 0.0, 1.0);
  let ok_lo = vec3<f32>(0.14, 0.58, 0.52);
  let ok_hi = vec3<f32>(0.68, 0.91, 0.76);
  return mix(ok_lo, ok_hi, t);
}

fn color_raking_sun(gx: f32, gy: f32, n: vec3<f32>) -> vec3<f32> {
  // sunAzimuthDeg is CW from North (+Y). So East = sin(az), North = cos(az).
  let az = u.wipe_sun.z;
  let el = u.wipe_sun.w;
  let cos_el = cos(el);
  let sun_dir = normalize(vec3<f32>(sin(az) * cos_el, cos(az) * cos_el, sin(el)));

  // Heightfield shadow ray march in grid cells
  let dx = u.grid_info.x;
  let z0 = sample_bilinear(0u, gx, gy);
  let horiz_step_cells = 1.5;
  let horiz_step_m = horiz_step_cells * dx;
  let step_xy = normalize(vec2<f32>(sin(az), cos(az))) * horiz_step_cells;
  let dz_per_step = tan(el) * horiz_step_m;

  var shadow = 1.0;
  var cur_xy = vec2<f32>(gx, gy);
  for (var i = 1; i <= 22; i++) {
    cur_xy += step_xy;
    if (cur_xy.x < 0.0 || cur_xy.y < 0.0 || cur_xy.x >= f32(u.grid_dims.x) || cur_xy.y >= f32(u.grid_dims.y)) {
      break;
    }
    let ray_z = z0 + dz_per_step * f32(i);
    let terrain_z = sample_bilinear(0u, cur_xy.x, cur_xy.y);
    if (terrain_z > ray_z + 0.04) {
      shadow = 0.22;
      break;
    }
  }

  let ndotl = max(dot(n, sun_dir), 0.0);
  let view_dir = normalize(u.cam_eye.xyz - vec3<f32>(0.0));
  let half_vec = normalize(sun_dir + view_dir);
  let spec = pow(max(dot(n, half_vec), 0.0), 28.0) * 0.24 * shadow;

  let svf = sample_bilinear(6u, gx, gy);
  let base_albedo = vec3<f32>(0.68, 0.69, 0.67);
  let ambient = 0.24 * (0.55 + 0.45 * svf) * vec3<f32>(0.66, 0.74, 0.85);
  let direct = 0.95 * ndotl * shadow * vec3<f32>(1.0, 0.94, 0.84);
  return clamp(base_albedo * (ambient + direct) + vec3<f32>(spec), vec3<f32>(0.0), vec3<f32>(1.0));
}

fn unavailable_pattern(uv: vec2<f32>) -> vec3<f32> {
  let check = step(0.5, fract(uv.x * 16.0)) * step(0.5, fract(uv.y * 16.0));
  return mix(vec3<f32>(0.14, 0.16, 0.20), vec3<f32>(0.24, 0.14, 0.16), check);
}

fn eval_layer(
  layer_id: u32,
  gx: f32,
  gy: f32,
  uv: vec2<f32>,
  n: vec3<f32>,
  c_usa10: vec3<f32>,
  c_old10: vec3<f32>,
  c_gazo1: vec3<f32>,
  c_seaml: vec3<f32>
) -> vec3<f32> {
  let subtle_shade = 0.85 + 0.15 * max(n.z, 0.0);
  switch (layer_id) {
    case 0u: { // Chiba RRIM
      let r = sample_bilinear(3u, gx, gy);
      let g = sample_bilinear(4u, gx, gy);
      let b = sample_bilinear(5u, gx, gy);
      return vec3<f32>(r, g, b);
    }
    case 1u: { // Live Raking-Light Sun
      return color_raking_sun(gx, gy, n);
    }
    case 2u: { // Zaksek SVF
      return color_svf(sample_bilinear(6u, gx, gy));
    }
    case 3u: { // Hesse LRM
      return color_lrm(sample_bilinear(7u, gx, gy));
    }
    case 4u: { // Drainage Violation
      return color_flow_violation(sample_bilinear(9u, gx, gy));
    }
    case 5u: { // Ground Confidence rho_gnd
      return color_rho_gnd(sample_bilinear(2u, gx, gy), gx, gy);
    }
    case 6u: { // GSI 1945 ort_USA10
      if (u.flags.y < 0.5) { return unavailable_pattern(uv); }
      return c_usa10 * subtle_shade;
    }
    case 7u: { // GSI 1965 ort_old10
      if (u.flags.z < 0.5) { return unavailable_pattern(uv); }
      return c_old10 * subtle_shade;
    }
    case 8u: { // GSI 1975 gazo1
      if (u.flags.w < 0.5) { return unavailable_pattern(uv); }
      return c_gazo1 * subtle_shade;
    }
    case 10u: {
      // Categorical nearest-cell lookup preserves blackout boundaries.
      let code = i32(read_cell(10u, i32(round(gx)), i32(round(gy))));
      switch code {
        case 0: { return vec3<f32>(141.,39.,69.)/255.; }
        case 1: { return vec3<f32>(85.,88.,103.)/255.; }
        case 2: { return vec3<f32>(231.,173.,103.)/255.; }
        case 3: { return vec3<f32>(169.,211.,191.)/255.; }
        case 4: { return vec3<f32>(86.,166.,158.)/255.; }
        case 5: { return vec3<f32>(34.,100.,113.)/255.; }
        default: { return unavailable_pattern(uv); }
      }
    }
    default: { // GSI Today seamlessphoto (9u)
      if (u.flags2.x < 0.5) { return unavailable_pattern(uv); }
      return c_seaml * subtle_shade;
    }
  }
}

@fragment
fn fs_main(in: VsOut) -> @location(0) vec4<f32> {
  // Sample all aerial textures in uniform control flow
  let c_usa10 = textureSample(tex_usa10, aerial_sampler, in.uv).rgb;
  let c_old10 = textureSample(tex_old10, aerial_sampler, in.uv).rgb;
  let c_gazo1 = textureSample(tex_gazo1, aerial_sampler, in.uv).rgb;
  let c_seaml = textureSample(tex_seamless, aerial_sampler, in.uv).rgb;

  let gx = in.grid_coord.x;
  let gy = in.grid_coord.y;
  let n = compute_normal_metric(gx, gy);

  var col = eval_layer(u.grid_dims.z, gx, gy, in.uv, n, c_usa10, c_old10, c_gazo1, c_seaml);

  if (u.wipe_sun.x > 0.5) {
    let screen_norm_x = in.clip_pos.x / max(u.viewport.x, 1.0);
    if (screen_norm_x > u.wipe_sun.y) {
      col = eval_layer(u.grid_dims.w, gx, gy, in.uv, n, c_usa10, c_old10, c_gazo1, c_seaml);
    }
    let dist_px = abs(screen_norm_x - u.wipe_sun.y) * u.viewport.x;
    if (dist_px < 1.5 * u.flags2.y) {
      col = vec3<f32>(0.98, 0.85, 0.32);
    }
  }

  // Optional 10m metric grid overlay
  if (u.flags.x > 0.5) {
    let dx = u.grid_info.x;
    let mx = fract((gx * dx) / 10.0);
    let my = fract((gy * dx) / 10.0);
    if (mx < 0.025 || my < 0.025) {
      col = mix(col, vec3<f32>(0.55, 0.78, 0.95), 0.25);
    }
  }

  return vec4<f32>(col, 1.0);
}
`,qt=`struct Uniforms {
  view_proj: mat4x4<f32>,
  cam_eye: vec4<f32>,       // xyz = eye, w = z_exag
  grid_info: vec4<f32>,     // x = dx, y = z_min, z = z_max, w = max_hag
  grid_dims: vec4<u32>,     // x = nx, y = ny, z = primary_layer, w = compare_layer
  wipe_sun: vec4<f32>,
  viewport: vec4<f32>,      // x = width_px, y = height_px, z = peel, w = point_size_m
  flags: vec4<f32>,
  flags2: vec4<f32>,
};

@group(0) @binding(0) var<uniform> u: Uniforms;
@group(0) @binding(1) var<storage, read> canopy_pts: array<vec4<f32>>;

struct VsOut {
  @builtin(position) clip_pos: vec4<f32>,
  @location(0) quad_uv: vec2<f32>,
  @location(1) color: vec3<f32>,
  @location(2) alpha: f32,
};

fn hash_u32(n: u32) -> f32 {
  var x = n;
  x = ((x >> 16u) ^ x) * 0x45d9f3bu;
  x = ((x >> 16u) ^ x) * 0x45d9f3bu;
  x = (x >> 16u) ^ x;
  return f32(x & 0x00ffffffu) / 16777215.0;
}

@vertex
fn vs_main(
  @builtin(vertex_index) vid: u32,
  @builtin(instance_index) iid: u32
) -> VsOut {
  var out: VsOut;

  let peel = clamp(u.viewport.z, 0.0, 1.0);
  if (peel <= 0.001) {
    out.clip_pos = vec4<f32>(0.0, 0.0, 2.0, 1.0);
    out.quad_uv = vec2<f32>(0.0);
    out.color = vec3<f32>(0.0);
    out.alpha = 0.0;
    return out;
  }

  let pt = canopy_pts[iid]; // rel_x, rel_y, z_abs, hag
  let hag = max(pt.w, 0.0);
  let hag_norm = clamp(hag / max(u.grid_info.w, 1.0), 0.0, 1.0);
  let h = hash_u32(iid + 1u);

  // Rank in [0.02, 0.999]; upper canopy and denser points strip away first as peel goes 1 -> 0
  let rank = clamp(0.02 + 0.56 * hag_norm + 0.419 * h, 0.02, 0.999);
  let margin = peel * 1.08 - rank;
  if (margin <= 0.0) {
    out.clip_pos = vec4<f32>(0.0, 0.0, 2.0, 1.0);
    out.quad_uv = vec2<f32>(0.0);
    out.color = vec3<f32>(0.0);
    out.alpha = 0.0;
    return out;
  }

  let dx = u.grid_info.x;
  let width_m = f32(u.grid_dims.x) * dx;
  let height_m = f32(u.grid_dims.y) * dx;
  let z_mid = 0.5 * (u.grid_info.y + u.grid_info.z);

  let wx = pt.x - width_m * 0.5;
  let wy = pt.y - height_m * 0.5;
  let wz = (pt.z - z_mid) * u.cam_eye.w;
  let center = vec3<f32>(wx, wy, wz);

  let to_cam = normalize(u.cam_eye.xyz - center);
  let ref_up = select(vec3<f32>(0.0, 0.0, 1.0), vec3<f32>(0.0, 1.0, 0.0), abs(to_cam.z) > 0.995);
  let right = normalize(cross(ref_up, to_cam));
  let up = cross(to_cam, right);

  var corners = array<vec2<f32>, 6>(
    vec2<f32>(-1.0, -1.0),
    vec2<f32>( 1.0, -1.0),
    vec2<f32>( 1.0,  1.0),
    vec2<f32>(-1.0, -1.0),
    vec2<f32>( 1.0,  1.0),
    vec2<f32>(-1.0,  1.0)
  );
  let corner = corners[vid];
  let scale = clamp(margin / 0.12, 0.0, 1.0);
  let radius = u.viewport.w * (0.65 + 0.55 * hag_norm) * scale;
  let world_pos = center + (right * corner.x + up * corner.y) * radius;

  // Forest canopy vertical gradient: olive understory -> emerald mid -> sunlit chartreuse crown
  let c_low = vec3<f32>(0.36, 0.48, 0.24);
  let c_mid = vec3<f32>(0.15, 0.49, 0.30);
  let c_top = vec3<f32>(0.54, 0.80, 0.34);
  var col = c_mid;
  if (hag_norm < 0.35) {
    col = mix(c_low, c_mid, hag_norm / 0.35);
  } else {
    col = mix(c_mid, c_top, (hag_norm - 0.35) / 0.65);
  }
  // Subtle micro-variation
  col *= 0.86 + 0.24 * h;

  out.clip_pos = u.view_proj * vec4<f32>(world_pos, 1.0);
  out.quad_uv = corner;
  out.color = col;
  out.alpha = scale;
  return out;
}

@fragment
fn fs_main(in: VsOut) -> @location(0) vec4<f32> {
  if (in.alpha <= 0.05) {
    discard;
  }
  let r2 = dot(in.quad_uv, in.quad_uv);
  if (r2 > 1.0) {
    discard;
  }
  // Subtle spherical shading on foliage splat
  let shade = 0.72 + 0.28 * (1.0 - r2);
  return vec4<f32>(in.color * shade, 1.0);
}
`,Ht=`struct Uniforms {
  view_proj: mat4x4<f32>,
};

@group(0) @binding(0) var<uniform> u: Uniforms;

struct VsOut {
  @builtin(position) clip_pos: vec4<f32>,
  @location(0) kind: f32,
};

@vertex
fn vs_main(@location(0) pos_kind: vec4<f32>) -> VsOut {
  var out: VsOut;
  out.clip_pos = u.view_proj * vec4<f32>(pos_kind.xyz, 1.0);
  out.kind = pos_kind.w;
  return out;
}

@fragment
fn fs_main(in: VsOut) -> @location(0) vec4<f32> {
  if (in.kind > 0.5) {
    // Endpoint beacon (amber)
    return vec4<f32>(1.0, 0.76, 0.16, 1.0);
  }
  // Transect ribbon (bright cyan)
  return vec4<f32>(0.15, 0.92, 0.98, 1.0);
}
`,st=176,Kt=64;function lt(t){const e=te.find(n=>n.id===t);return e?e.shaderIndex:0}class Pe{adapter;device;format;sampler;placeholderTex;terrainBgl;canopyBgl;overlayBgl;terrainPipeline;canopyPipeline;overlayPipeline;constructor(e,n,r){this.adapter=e,this.device=n,this.format=r,this.sampler=n.createSampler({magFilter:"linear",minFilter:"linear",addressModeU:"clamp-to-edge",addressModeV:"clamp-to-edge"}),this.placeholderTex=n.createTexture({size:[1,1,1],format:"rgba8unorm",usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST|GPUTextureUsage.RENDER_ATTACHMENT}),n.queue.writeTexture({texture:this.placeholderTex},new Uint8Array([32,36,44,255]),{bytesPerRow:4},[1,1,1]),this.terrainBgl=n.createBindGroupLayout({label:"terrain-bgl",entries:[{binding:0,visibility:GPUShaderStage.VERTEX|GPUShaderStage.FRAGMENT,buffer:{type:"uniform"}},{binding:1,visibility:GPUShaderStage.VERTEX|GPUShaderStage.FRAGMENT,buffer:{type:"read-only-storage"}},{binding:2,visibility:GPUShaderStage.FRAGMENT,sampler:{type:"filtering"}},{binding:3,visibility:GPUShaderStage.FRAGMENT,texture:{sampleType:"float"}},{binding:4,visibility:GPUShaderStage.FRAGMENT,texture:{sampleType:"float"}},{binding:5,visibility:GPUShaderStage.FRAGMENT,texture:{sampleType:"float"}},{binding:6,visibility:GPUShaderStage.FRAGMENT,texture:{sampleType:"float"}}]}),this.canopyBgl=n.createBindGroupLayout({label:"canopy-bgl",entries:[{binding:0,visibility:GPUShaderStage.VERTEX|GPUShaderStage.FRAGMENT,buffer:{type:"uniform"}},{binding:1,visibility:GPUShaderStage.VERTEX,buffer:{type:"read-only-storage"}}]}),this.overlayBgl=n.createBindGroupLayout({label:"overlay-bgl",entries:[{binding:0,visibility:GPUShaderStage.VERTEX,buffer:{type:"uniform"}}]});const a=n.createShaderModule({label:"terrain.wgsl",code:Wt}),l=n.createShaderModule({label:"canopy.wgsl",code:qt}),s=n.createShaderModule({label:"overlay.wgsl",code:Ht});this.terrainPipeline=n.createRenderPipeline({label:"terrain-pipeline",layout:n.createPipelineLayout({bindGroupLayouts:[this.terrainBgl]}),vertex:{module:a,entryPoint:"vs_main"},fragment:{module:a,entryPoint:"fs_main",targets:[{format:r}]},primitive:{topology:"triangle-list",cullMode:"none"},depthStencil:{format:"depth24plus",depthWriteEnabled:!0,depthCompare:"less"}}),this.canopyPipeline=n.createRenderPipeline({label:"canopy-pipeline",layout:n.createPipelineLayout({bindGroupLayouts:[this.canopyBgl]}),vertex:{module:l,entryPoint:"vs_main"},fragment:{module:l,entryPoint:"fs_main",targets:[{format:r}]},primitive:{topology:"triangle-list",cullMode:"none"},depthStencil:{format:"depth24plus",depthWriteEnabled:!0,depthCompare:"less"}}),this.overlayPipeline=n.createRenderPipeline({label:"overlay-pipeline",layout:n.createPipelineLayout({bindGroupLayouts:[this.overlayBgl]}),vertex:{module:s,entryPoint:"vs_main",buffers:[{arrayStride:16,attributes:[{shaderLocation:0,offset:0,format:"float32x4"}]}]},fragment:{module:s,entryPoint:"fs_main",targets:[{format:r}]},primitive:{topology:"triangle-list",cullMode:"none"},depthStencil:{format:"depth24plus",depthWriteEnabled:!0,depthCompare:"less-equal"}})}static async create(){if(!navigator.gpu)throw new Error("WebGPU is not supported in this browser (navigator.gpu missing).");const e=await navigator.gpu.requestAdapter({powerPreference:"high-performance"});if(!e)throw new Error("No WebGPU adapter found.");const n=await e.requestDevice(),r=navigator.gpu.getPreferredCanvasFormat();return new Pe(e,n,r)}}class ct{gpu;canvas;context;uniformBuffer;overlayUniformBuffer;uniformData=new ArrayBuffer(st);uniformF32=new Float32Array(this.uniformData);uniformU32=new Uint32Array(this.uniformData);depthTex=null;depthW=0;depthH=0;gridBuffer=null;indexBuffer=null;indexCount=0;canopyBuffer=null;canopyCount=0;aerialTextures={};textureFlags={ort_USA10:!1,ort_old10:!1,gazo1:!1,seamlessphoto:!1};terrainBindGroup=null;canopyBindGroup=null;overlayBindGroup;overlayVertexBuffer=null;overlayVertexCount=0;loadedData=null;constructor(e,n){this.gpu=e,this.canvas=n;const r=n.getContext("webgpu");if(!r)throw new Error("Failed to acquire WebGPU canvas context.");this.context=r,this.context.configure({device:e.device,format:e.format,alphaMode:"opaque"}),this.uniformBuffer=e.device.createBuffer({size:st,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.overlayUniformBuffer=e.device.createBuffer({size:Kt,usage:GPUBufferUsage.UNIFORM|GPUBufferUsage.COPY_DST}),this.overlayBindGroup=e.device.createBindGroup({layout:e.overlayBgl,entries:[{binding:0,resource:{buffer:this.overlayUniformBuffer}}]})}uploadCandidateData(e){this.loadedData=e;const n=this.gpu.device,{nx:r,ny:a,n_canopy_pts:l}=e.pack.header;this.gridBuffer?.destroy(),this.indexBuffer?.destroy(),this.canopyBuffer?.destroy();for(const h of Object.values(this.aerialTextures))h?.destroy();this.aerialTextures={};const s=e.pack.rawGridBuffer.byteLength;this.gridBuffer=n.createBuffer({label:"grid-storage",size:Math.max(16,s+e.coverage.byteLength),usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),n.queue.writeBuffer(this.gridBuffer,0,e.pack.rawGridBuffer.buffer,e.pack.rawGridBuffer.byteOffset,s),n.queue.writeBuffer(this.gridBuffer,s,e.coverage.buffer,e.coverage.byteOffset,e.coverage.byteLength);const o=(r-1)*(a-1),d=new Uint32Array(o*6);let v=0;for(let h=0;h<a-1;h++)for(let y=0;y<r-1;y++){const m=h*r+y,S=m+1,E=(h+1)*r+y,L=E+1;d[v++]=m,d[v++]=S,d[v++]=L,d[v++]=m,d[v++]=L,d[v++]=E}this.indexCount=d.length,this.indexBuffer=n.createBuffer({label:"terrain-indices",size:d.byteLength,usage:GPUBufferUsage.INDEX|GPUBufferUsage.COPY_DST}),n.queue.writeBuffer(this.indexBuffer,0,d),this.canopyCount=l;const p=Math.max(16,e.pack.canopyPts.byteLength);this.canopyBuffer=n.createBuffer({label:"canopy-pts",size:p,usage:GPUBufferUsage.STORAGE|GPUBufferUsage.COPY_DST}),e.pack.canopyPts.byteLength>0&&n.queue.writeBuffer(this.canopyBuffer,0,e.pack.canopyPts.buffer,e.pack.canopyPts.byteOffset,e.pack.canopyPts.byteLength);const z=["ort_USA10","ort_old10","gazo1","seamlessphoto"];for(const h of z){const y=e.textures[h];if(y){const m=n.createTexture({label:`aerial-${h}`,size:[y.width,y.height,1],format:"rgba8unorm",usage:GPUTextureUsage.TEXTURE_BINDING|GPUTextureUsage.COPY_DST|GPUTextureUsage.RENDER_ATTACHMENT});n.queue.copyExternalImageToTexture({source:y},{texture:m},[y.width,y.height]),this.aerialTextures[h]=m,this.textureFlags[h]=!0}else this.textureFlags[h]=!1}const w=h=>(this.aerialTextures[h]??this.gpu.placeholderTex).createView();this.terrainBindGroup=n.createBindGroup({layout:this.gpu.terrainBgl,entries:[{binding:0,resource:{buffer:this.uniformBuffer}},{binding:1,resource:{buffer:this.gridBuffer}},{binding:2,resource:this.gpu.sampler},{binding:3,resource:w("ort_USA10")},{binding:4,resource:w("ort_old10")},{binding:5,resource:w("gazo1")},{binding:6,resource:w("seamlessphoto")}]}),this.canopyBindGroup=n.createBindGroup({layout:this.gpu.canopyBgl,entries:[{binding:0,resource:{buffer:this.uniformBuffer}},{binding:1,resource:{buffer:this.canopyBuffer}}]})}updateCaliperOverlay(e,n){if(this.overlayVertexBuffer?.destroy(),this.overlayVertexBuffer=null,this.overlayVertexCount=0,!e||!this.loadedData||e.samples.length<2)return;const{nx:r,ny:a,dx:l,z_min:s,z_max:o}=this.loadedData.pack.header,d=r*l*.5,v=a*l*.5,p=.5*(s+o),z=e.samples,w=e.p1.relX-e.p0.relX,h=e.p1.relY-e.p0.relY,y=Math.max(1e-4,Math.hypot(w,h)),m=-h/y*.45,S=w/y*.45,E=z.length-1,L=E*6+24,P=new Float32Array(L*4);let A=0;const B=(_,g,M,C)=>{P[A++]=_,P[A++]=g,P[A++]=M,P[A++]=C};for(let _=0;_<E;_++){const g=z[_],M=z[_+1],C=g.relX-d,I=g.relY-v,G=(g.zGnd-p)*n+.25,V=M.relX-d,Z=M.relY-v,ne=(M.zGnd-p)*n+.25;B(C-m,I-S,G,0),B(C+m,I+S,G,0),B(V+m,Z+S,ne,0),B(C-m,I-S,G,0),B(V+m,Z+S,ne,0),B(V-m,Z-S,ne,0)}const F=[e.p0,e.p1],x=1.1,u=3.2;for(const _ of F){const g=_.relX-d,M=_.relY-v,C=(_.zGnd-p)*n+.25;B(g-x,M,C,1),B(g+x,M,C,1),B(g,M,C+u,1),B(g,M-x,C,1),B(g,M+x,C,1),B(g,M,C+u,1),B(g-x,M-x,C+.1,1),B(g+x,M-x,C+.1,1),B(g+x,M+x,C+.1,1),B(g-x,M-x,C+.1,1),B(g+x,M+x,C+.1,1),B(g-x,M+x,C+.1,1)}this.overlayVertexCount=L,this.overlayVertexBuffer=this.gpu.device.createBuffer({label:"caliper-overlay-verts",size:P.byteLength,usage:GPUBufferUsage.VERTEX|GPUBufferUsage.COPY_DST}),this.gpu.device.queue.writeBuffer(this.overlayVertexBuffer,0,P)}render(e,n){if(!this.loadedData||!this.terrainBindGroup||!this.indexBuffer)return;const r=Math.min(window.devicePixelRatio||1,2),a=Math.max(1,this.canvas.clientWidth),l=Math.max(1,this.canvas.clientHeight),s=Math.min(4096,Math.max(1,Math.round(a*r))),o=Math.min(4096,Math.max(1,Math.round(l*r)));(this.canvas.width!==s||this.canvas.height!==o)&&(this.canvas.width=s,this.canvas.height=o),(!this.depthTex||this.depthW!==s||this.depthH!==o)&&(this.depthTex?.destroy(),this.depthTex=this.gpu.device.createTexture({size:[s,o,1],format:"depth24plus",usage:GPUTextureUsage.RENDER_ATTACHMENT}),this.depthW=s,this.depthH=o);const d=s/o,{eye:v,viewProj:p}=e.getViewProj(d),{header:z,maxHag:w}=this.loadedData.pack;this.uniformF32.set(p,0),this.uniformF32[16]=v[0],this.uniformF32[17]=v[1],this.uniformF32[18]=v[2],this.uniformF32[19]=n.zExag,this.uniformF32[20]=z.dx,this.uniformF32[21]=z.z_min,this.uniformF32[22]=z.z_max,this.uniformF32[23]=w,this.uniformU32[24]=z.nx,this.uniformU32[25]=z.ny,this.uniformU32[26]=lt(n.primaryLayer),this.uniformU32[27]=lt(n.compareLayer),this.uniformF32[28]=n.splitEnabled?1:0,this.uniformF32[29]=n.splitX,this.uniformF32[30]=n.sunAzimuthDeg*Math.PI/180,this.uniformF32[31]=n.sunElevationDeg*Math.PI/180,this.uniformF32[32]=s,this.uniformF32[33]=o,this.uniformF32[34]=n.peel,this.uniformF32[35]=n.pointSizePx,this.uniformF32[36]=n.showGridOverlay?1:0,this.uniformF32[37]=this.textureFlags.ort_USA10?1:0,this.uniformF32[38]=this.textureFlags.ort_old10?1:0,this.uniformF32[39]=this.textureFlags.gazo1?1:0,this.uniformF32[40]=this.textureFlags.seamlessphoto?1:0,this.uniformF32[41]=r,this.uniformF32[42]=0,this.uniformF32[43]=0,this.gpu.device.queue.writeBuffer(this.uniformBuffer,0,this.uniformData),this.gpu.device.queue.writeBuffer(this.overlayUniformBuffer,0,p.buffer,p.byteOffset,p.byteLength);const h=this.context.getCurrentTexture().createView(),y=this.gpu.device.createCommandEncoder(),m=y.beginRenderPass({colorAttachments:[{view:h,clearValue:{r:.043,g:.055,b:.078,a:1},loadOp:"clear",storeOp:"store"}],depthStencilAttachment:{view:this.depthTex.createView(),depthClearValue:1,depthLoadOp:"clear",depthStoreOp:"store"}});m.setPipeline(this.gpu.terrainPipeline),m.setBindGroup(0,this.terrainBindGroup),m.setIndexBuffer(this.indexBuffer,"uint32"),m.drawIndexed(this.indexCount),n.peel>.001&&this.canopyCount>0&&this.canopyBindGroup&&(m.setPipeline(this.gpu.canopyPipeline),m.setBindGroup(0,this.canopyBindGroup),m.draw(6,this.canopyCount)),this.overlayVertexCount>0&&this.overlayVertexBuffer&&(m.setPipeline(this.gpu.overlayPipeline),m.setBindGroup(0,this.overlayBindGroup),m.setVertexBuffer(0,this.overlayVertexBuffer),m.draw(this.overlayVertexCount)),m.end(),this.gpu.device.queue.submit([y.finish()])}dispose(){this.uniformBuffer.destroy(),this.overlayUniformBuffer.destroy(),this.depthTex?.destroy(),this.gridBuffer?.destroy(),this.indexBuffer?.destroy(),this.canopyBuffer?.destroy(),this.overlayVertexBuffer?.destroy();for(const e of Object.values(this.aerialTextures))e?.destroy()}}const Zt={rrim:"Chiba RRIM: Slope (Red) + Differential Openness I_10",raking_sun:"Live Raking-Light Sun: Real-time WGSL shadows + Lambertian relief",svf:"Zaksek SVF: Dark indigo (sheltered pits/ditches) -> Ivory (exposed crests)",lrm:"Hesse LRM: Cobalt (-2m cut/ditch) -> Slate (0m) -> Amber (+2m mound/wall)",flow_violation:"Drainage Violation: Slate (0.0) -> Purple -> Orange -> Yellow (1.0)",coverage:"Local density below 0.5 pts/m² is excluded. Other colors show the 16 m mean.",rho_gnd:"Ground Confidence: RED WARNING < 0.5 pts/m² (TIN hallucination risk)",ort_USA10:"GSI 1945 (ort_USA10) draped on 0.5m bare-earth mesh",ort_old10:"GSI 1965 (ort_old10) draped on 0.5m bare-earth mesh",gazo1:"GSI 1975 (gazo1) draped on 0.5m bare-earth mesh",seamlessphoto:"GSI Today (seamlessphoto) draped on 0.5m bare-earth mesh"};function Jt(t){switch(t){case"Class A":return"badge badge-a";case"Class B":return"badge badge-b";case"Class C":return"badge badge-c";default:return"badge badge-rej"}}function Qt(t,e,n){const r=t.getContext("2d");if(!r)return;const a=t.width,l=t.height,s=a*.5,o=l*.5,d=Math.min(s,o)-7;r.clearRect(0,0,a,l),r.strokeStyle="#253348",r.lineWidth=1;for(const h of[1,.66,.33])r.beginPath(),r.arc(s,o,d*h,0,Math.PI*2),r.stroke();r.beginPath(),r.moveTo(s-d,o),r.lineTo(s+d,o),r.moveTo(s,o-d),r.lineTo(s,o+d),r.stroke(),r.fillStyle="#7c8ea6",r.font="9px ui-monospace, monospace",r.textAlign="center",r.fillText("N",s,9);const v=e*Math.PI/180,p=Math.max(.05,Math.min(1,(90-n)/90)),z=s+Math.sin(v)*d*p,w=o-Math.cos(v)*d*p;r.strokeStyle="rgba(250, 204, 21, 0.55)",r.lineWidth=1.5,r.beginPath(),r.moveTo(s,o),r.lineTo(z,w),r.stroke(),r.fillStyle="#facc15",r.beginPath(),r.arc(z,w,5,0,Math.PI*2),r.fill(),r.strokeStyle="#0b0f16",r.lineWidth=1.5,r.stroke()}async function en(){const t=document.getElementById("status-banner"),e=i=>{t.textContent=i,t.classList.remove("hidden")},n=document.getElementById("gpu-canvas-primary"),r=document.getElementById("gpu-canvas-compare"),a=document.getElementById("compare-pane"),l=document.getElementById("inspector"),s=document.getElementById("study-zone-label"),o=document.getElementById("triage-pills"),d=document.getElementById("candidate-select"),v=document.getElementById("select-rejected-compare"),p=document.getElementById("rejected-picker-row"),z=document.getElementById("btn-side-by-side"),w=document.getElementById("btn-caliper"),h=document.getElementById("chk-confirmed-only"),y=document.getElementById("btn-export-gpx"),m=document.getElementById("btn-toggle-inspector"),S=document.getElementById("slider-peel"),E=document.getElementById("val-peel"),L=document.getElementById("slider-zexag"),P=document.getElementById("val-zexag"),A=document.getElementById("chk-split-wipe"),B=document.getElementById("select-primary-layer"),F=document.getElementById("select-compare-layer"),x=document.getElementById("slider-split-x"),u=document.getElementById("val-split-x"),_=document.getElementById("split-overlay"),g=document.getElementById("split-handle"),M=document.getElementById("split-label-left"),C=document.getElementById("split-label-right"),I=document.getElementById("layer-legend"),G=document.getElementById("sun-gizmo"),V=document.getElementById("slider-sun-az"),Z=document.getElementById("slider-sun-el"),ne=document.getElementById("val-sun-az"),ht=document.getElementById("val-sun-el"),pt=document.getElementById("val-sun-readout"),me=document.getElementById("caliper-canvas"),mt=document.getElementById("btn-clear-caliper"),Ie=document.getElementById("ro-wall"),Ge=document.getElementById("ro-slope"),Te=document.getElementById("ro-lrm"),Ae=document.getElementById("ro-rho"),Fe=document.getElementById("ro-rho-card"),gt=document.getElementById("hud-cid"),Ue=document.getElementById("hud-class"),ge=document.getElementById("hud-annot"),yt=document.getElementById("hud-meta"),xt=document.getElementById("hud-rho-warn"),ye=document.getElementById("hud-rej-reason"),_t=document.getElementById("cmp-cid"),vt=document.getElementById("cmp-meta"),bt=document.getElementById("cmp-rej-reason"),Re=document.getElementById("gsi-credit"),wt=document.getElementById("usa10-unavailable"),Et=document.getElementById("val-qval"),Mt=document.getElementById("cand-notes"),ke=Array.from(document.querySelectorAll(".btn-annot"));for(const i of te){const c=document.createElement("option");c.value=i.id,c.textContent=i.label,B.appendChild(c);const f=document.createElement("option");f.value=i.id,f.textContent=i.label,F.appendChild(f)}B.value="rrim",F.value="svf";let xe;try{xe=await Pe.create()}catch(i){e(`WebGPU initialization failed: ${i.message}`);return}let W;try{W=await Rt()}catch(i){e(`Data load error: ${i.message}`);return}const H=W.fieldSupport,_e=document.getElementById("coverage-legend"),ve=document.getElementById("support-summary"),Bt=["[0.5, 1.0)","[1.0, 2.5)","[2.5, 5.0)",">= 5.0"],$e=i=>H?.calibration?.[Bt[i-2]];if(H){document.getElementById("coverage-map-link").classList.remove("hidden");const i=document.createElement("strong");i.textContent="Ground pts/m² · calibration recovery",_e.append(i),H.labels.forEach((c,f)=>{const U=document.createElement("div"),R=document.createElement("i");R.style.backgroundColor=H.colors[f];const T=$e(f),$=T?`${T.detected}/${T.total} sites`:f===0?"Excluded":"Untested",N=f===0?"<0.5 local":f===1?"<0.5 context":c;U.append(R,document.createTextNode(`${N} · ${$}`)),_e.append(U)})}else for(const i of[B,F]){const c=i.querySelector('option[value="coverage"]');c&&(c.disabled=!0)}s.textContent=W.study_zone?.name||"Seeing Space · Forest X-Ray",W.study_zone?.gsi_attribution&&(Re.textContent=W.study_zone.gsi_attribution);const se=new ct(xe,n),De=new ct(xe,r),j=new Tt,b={peel:1,zExag:1.5,primaryLayer:"rrim",compareLayer:"svf",splitEnabled:!1,splitX:.5,sunAzimuthDeg:315,sunElevationDeg:18,pointSizePx:.42,showGridOverlay:!1};let be="All",K=Xt(),q=!1,re=!1,k=null,we=null,O=null,oe=null;const Oe=new Map,Ve=new Map;let Ee=!0;const D=()=>{Ee=!0},Ne=async i=>{const c=Oe.get(i.candidate_id);if(c)return c;const f=await Nt(i,W.fieldSupport);Oe.set(i.candidate_id,f);const{nx:U,ny:R,z_min:T,z_max:$}=f.pack.header,N=Math.floor(R/2)*U+Math.floor(U/2),X=f.pack.layers.z_gnd[N]??.5*(T+$);return Ve.set(i.candidate_id,X),f},Y=W.candidates,ae=(i,c)=>{const f=document.getElementById(i);f&&(f.textContent=String(c))};ae("cnt-all",Y.length),ae("cnt-a",Y.filter(i=>i.temporal_class==="Class A").length),ae("cnt-b",Y.filter(i=>i.temporal_class==="Class B").length),ae("cnt-c",Y.filter(i=>i.temporal_class==="Class C").length),ae("cnt-rej",Y.filter(i=>i.temporal_class==="Rejected").length);const le=Yt(Y);for(const i of le){const c=document.createElement("option");c.value=i.candidate_id,c.textContent=`${i.candidate_id} · ${i.morphology} (${i.rejection_reason??"rejected"})`,v.appendChild(c)}const Xe=()=>{const i=!!(k&&(k.textures.ort_USA10||k.textures.ort_old10||k.textures.gazo1||k.textures.seamlessphoto)),c=(W.study_zone?.gsi_layers_available?.length??0)>0,f=te.find(R=>R.id===b.primaryLayer)?.isAerial||b.splitEnabled&&te.find(R=>R.id===b.compareLayer)?.isAerial;Re.classList.toggle("hidden",!(i||c||f));const U=!!(k&&!k.ortUsa10Available);wt.classList.toggle("hidden",!U)},je=()=>{const i=k?.candidate.candidate_id,c=i?K[i]:void 0;for(const f of ke)f.classList.toggle("active",f.dataset.annot===c);c?(ge.textContent=c,ge.classList.remove("hidden")):ge.classList.add("hidden")},ce=()=>{if(Ce(me,O),se.updateCaliperOverlay(O,b.zExag),!O){Ie.textContent="—",Ge.textContent="—",Te.textContent="—",Ae.textContent="—",Fe.classList.remove("warn"),D();return}Ie.textContent=`${O.wallHeightM.toFixed(2)} m`,Ge.textContent=`${O.scarpSlopeDeg.toFixed(1)}°`,Te.textContent=`${O.localReliefM.toFixed(2)} m`,Ae.textContent=`${O.minRhoGnd.toFixed(2)} / ${O.meanRhoGnd.toFixed(2)}`,Fe.classList.toggle("warn",O.minRhoGnd<.5),D()},zt=i=>{const c=H?.candidates[i.candidate_id];if(ve.replaceChildren(),H&&c){const U=document.createElement("strong");U.textContent="Ground support";const R=document.createElement("p"),T=(100*c.native_band_cells[0]/c.window_cells).toFixed(0),$=$e(c.code);if(R.textContent=`Centre ${c.center_rho.toFixed(2)} pts/m². The 16 m square averages ${c.mean_16m.toFixed(2)} pts/m², with ${T}% in blackout. `+($?`This density band recovered ${$.detected} of ${$.total} calibration sites.`:"This position is outside the calibrated search bands."),ve.append(U,R),c.imagery_review){const N=document.createElement("p");N.textContent=(c.imagery_review.field_priority==="hold"?"Field shortlist on hold. ":"Aerial review. ")+c.imagery_review.notes,ve.append(N)}}gt.textContent=i.candidate_id,Ue.textContent=i.temporal_class,Ue.className=Jt(i.temporal_class),yt.textContent=`${i.morphology} · wall ${i.wall_height_m.toFixed(1)}m · scarp ${i.scarp_slope_deg.toFixed(1)}° · rho ${i.mean_rho_gnd.toFixed(2)}/m² · (${i.lat.toFixed(5)}, ${i.lon.toFixed(5)})`;const f=i.min_rho_gnd<.5||i.mean_rho_gnd<.5;xt.classList.toggle("hidden",!f),i.rejection_reason?(ye.textContent=`Rejected: ${i.rejection_reason}`,ye.classList.remove("hidden")):ye.classList.add("hidden"),Et.textContent=`q=${i.q_value.toExponential(2)}`,Mt.textContent=i.historical_notes||(i.osm_match?`OSM: ${i.osm_match}`:"No historical/OSM notes."),je(),Xe()},Ye=async i=>{const c=Y.find(f=>f.candidate_id===i);if(!(!c||!c.pack_file))try{const f=await Ne(c);k=f,se.uploadCandidateData(f),O=null,oe=null,ce(),zt(c),t.classList.add("hidden"),D()}catch(f){e(`Failed to load ${c.candidate_id}: ${f.message}`)}},We=async i=>{const c=Y.find(f=>f.candidate_id===i);if(!(!c||!c.pack_file))try{const f=await Ne(c);we=f,De.uploadCandidateData(f),_t.textContent=c.candidate_id;const U=H?.candidates[c.candidate_id];vt.textContent=`${c.morphology} · rho ${c.mean_rho_gnd.toFixed(2)}/m² · flow ${c.drainage_violation.toFixed(2)}`+(U?` · 16 m density ${U.mean_16m.toFixed(2)}/m²`:""),bt.textContent=c.rejection_reason?`Reason: ${c.rejection_reason}`:"Rejected decoy",D()}catch(f){e(`Failed to load decoy ${c.candidate_id}: ${f.message}`)}},qe=async()=>{const i=it(Y,be).filter(c=>!!c.pack_file);d.innerHTML="";for(const c of i){const f=document.createElement("option");f.value=c.candidate_id;const U=K[c.candidate_id],R=U?` [${U}]`:"";f.textContent=`${c.candidate_id} · ${c.morphology} · ${c.temporal_class}${R}`,d.appendChild(f)}if(i.length>0){const f=k&&i.some(U=>U.candidate_id===k.candidate.candidate_id)?k.candidate.candidate_id:i[0].candidate_id;d.value=f,await Ye(f)}};o.addEventListener("click",i=>{const c=i.target.closest(".pill");if(!(!c||!c.dataset.filter)){be=c.dataset.filter;for(const f of o.querySelectorAll(".pill"))f.classList.toggle("active",f===c);qe()}}),d.addEventListener("change",()=>{Ye(d.value)}),v.addEventListener("change",()=>{We(v.value)});const St=document.getElementById("viewport-area");z.addEventListener("click",()=>{if(q=!q,z.classList.toggle("active",q),a.classList.toggle("hidden",!q),St.classList.toggle("side-by-side",q),p.classList.toggle("hidden",!q),q&&!we&&le.length>0){const i=le.find(c=>!!c.pack_file)??le[0];v.value=i.candidate_id,We(i.candidate_id)}D()});const Ct=i=>{re=i,w.classList.toggle("active",re),n.classList.toggle("caliper-cursor",re)};w.addEventListener("click",()=>Ct(!re)),mt.addEventListener("click",()=>{O=null,oe=null,ce()});for(const i of ke)i.addEventListener("click",()=>{if(!k)return;const c=k.candidate.candidate_id,f=i.dataset.annot;K[c]===f?delete K[c]:K[c]=f,jt(K),je();const U=Array.from(d.options).find(R=>R.value===c);if(U){const R=k.candidate,T=K[c];U.textContent=`${R.candidate_id} · ${R.morphology} · ${R.temporal_class}${T?` [${T}]`:""}`}});y.addEventListener("click",()=>{let i=it(Y,be);h.checked&&(i=i.filter(f=>K[f.candidate_id]==="Confirmed"));const c=Ft(i,W.study_zone?.name||"PALIMPSEST",Ve);Ut(c,"palimpsest_filtered.gpx")}),m.addEventListener("click",()=>{l.classList.toggle("hidden"),D()});const He=i=>{const c=Math.max(0,Math.min(100,i));S.value=String(c),E.textContent=`${c}%`,b.peel=c/100,D()};S.addEventListener("input",()=>He(Number(S.value)));for(const i of document.querySelectorAll("[data-peel]"))i.addEventListener("click",()=>He(Number(i.dataset.peel??100)));L.addEventListener("input",()=>{b.zExag=Number(L.value),P.textContent=`${b.zExag.toFixed(1)}x`,se.updateCaliperOverlay(O,b.zExag),D()});const J=()=>{const i=te.find(f=>f.id===b.primaryLayer),c=te.find(f=>f.id===b.compareLayer);M.textContent=i?.shortLabel??b.primaryLayer,C.textContent=c?.shortLabel??b.compareLayer,_e.classList.toggle("hidden",!H||b.primaryLayer!=="coverage"&&!(b.splitEnabled&&b.compareLayer==="coverage")),I.textContent=Zt[b.primaryLayer],_.classList.toggle("hidden",!b.splitEnabled),g.style.left=`${(b.splitX*100).toFixed(2)}%`,u.textContent=`${Math.round(b.splitX*100)}%`,x.value=String(Math.round(b.splitX*100)),Xe(),D()};B.addEventListener("change",()=>{b.primaryLayer=B.value,J()}),F.addEventListener("change",()=>{b.compareLayer=F.value,J()}),A.addEventListener("change",()=>{b.splitEnabled=A.checked,J()}),x.addEventListener("input",()=>{b.splitX=Number(x.value)/100,J()});let Me=!1;g.addEventListener("pointerdown",i=>{i.stopPropagation(),Me=!0,g.setPointerCapture(i.pointerId)}),g.addEventListener("pointermove",i=>{if(!Me)return;const c=n.getBoundingClientRect(),f=(i.clientX-c.left)/Math.max(1,c.width);b.splitX=Math.max(.02,Math.min(.98,f)),J()}),g.addEventListener("pointerup",()=>{Me=!1});const de=()=>{V.value=String(Math.round(b.sunAzimuthDeg)),Z.value=String(Math.round(b.sunElevationDeg)),ne.textContent=`${Math.round(b.sunAzimuthDeg)}°`,ht.textContent=`${Math.round(b.sunElevationDeg)}°`,pt.textContent=`${Math.round(b.sunAzimuthDeg)}° / ${Math.round(b.sunElevationDeg)}°`,Qt(G,b.sunAzimuthDeg,b.sunElevationDeg),D()};V.addEventListener("input",()=>{b.sunAzimuthDeg=Number(V.value),de()}),Z.addEventListener("input",()=>{b.sunElevationDeg=Number(Z.value),de()});let Be=!1;const Ke=i=>{const c=G.getBoundingClientRect(),f=i.clientX-(c.left+c.width*.5),U=i.clientY-(c.top+c.height*.5),R=Math.min(c.width,c.height)*.5-7,T=Math.hypot(f,U),$=(Math.atan2(f,-U)*180/Math.PI+360)%360,N=Math.min(1,T/Math.max(1,R)),X=Math.max(2,Math.min(85,90-N*90));b.sunAzimuthDeg=$,b.sunElevationDeg=X,de()};G.addEventListener("pointerdown",i=>{Be=!0,G.setPointerCapture(i.pointerId),Ke(i)}),G.addEventListener("pointermove",i=>{Be&&Ke(i)}),G.addEventListener("pointerup",()=>{Be=!1}),document.getElementById("btn-view-oblique")?.addEventListener("click",()=>{j.reset(),D()}),document.getElementById("btn-view-top")?.addEventListener("click",()=>{j.setTopDown(),D()}),document.getElementById("btn-view-reset")?.addEventListener("click",()=>{j.reset(),D()});const Ze=document.getElementById("btn-toggle-grid");Ze.addEventListener("click",()=>{b.showGridOverlay=!b.showGridOverlay,Ze.classList.toggle("active",b.showGridOverlay),D()});const Je=(i,c)=>{let f="none",U=0,R=0;i.addEventListener("contextmenu",T=>T.preventDefault()),i.addEventListener("pointerdown",T=>{if(i.setPointerCapture(T.pointerId),U=T.clientX,R=T.clientY,c&&(re||T.shiftKey)&&T.button===0&&k){f="caliper";const $=i.getBoundingClientRect(),N=(T.clientX-$.left)/Math.max(1,$.width),X=(T.clientY-$.top)/Math.max(1,$.height),ie=j.screenToRay(N,X,$.width/Math.max(1,$.height));if(ie){const Q=rt(k.pack,b.zExag,ie.origin,ie.dir);Q&&(oe=Q,O=ot(k.pack,Q,Q,40),ce())}return}f=T.button===2||T.button===1||T.altKey?"pan":"orbit"}),i.addEventListener("pointermove",T=>{if(f==="none")return;const $=T.clientX-U,N=T.clientY-R;if(U=T.clientX,R=T.clientY,f==="caliper"&&k&&oe){const X=i.getBoundingClientRect(),ie=(T.clientX-X.left)/Math.max(1,X.width),Q=(T.clientY-X.top)/Math.max(1,X.height),ze=j.screenToRay(ie,Q,X.width/Math.max(1,X.height));if(ze){const et=rt(k.pack,b.zExag,ze.origin,ze.dir);et&&(O=ot(k.pack,oe,et,180),ce())}return}f==="orbit"?(j.orbit($,N),D()):f==="pan"&&(j.pan($,N),D())}),i.addEventListener("pointerup",()=>{f="none"}),i.addEventListener("wheel",T=>{T.preventDefault(),j.zoom(T.deltaY),D()},{passive:!1})};Je(n,!0),Je(r,!1),window.addEventListener("resize",()=>{Ce(me,O),D()});const Qe=()=>{Ee&&(Ee=!1,se.render(j,b),q&&we&&De.render(j,b)),requestAnimationFrame(Qe)};requestAnimationFrame(Qe),J(),de(),Ce(me,null),await qe(),window.__PALIMPSEST_VIEWER__={getState:()=>({candidateId:k?.candidate.candidate_id??null,peel:b.peel,primaryLayer:b.primaryLayer,compareLayer:b.compareLayer,splitEnabled:b.splitEnabled,splitX:b.splitX,sideBySide:q,caliper:O,ortUsa10Available:k?.ortUsa10Available??null})}}en();
