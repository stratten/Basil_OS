import { VERTEX_SRC, FRAGMENT_SRC } from './bubbleShaders';
import type { CapsuleUniforms } from './bubbleGeometry';

function compile(gl: WebGLRenderingContext, type: number, src: string): WebGLShader | null {
  const sh = gl.createShader(type);
  if (!sh) return null;
  gl.shaderSource(sh, src);
  gl.compileShader(sh);
  if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
    console.error('[bubble] shader compile failed:', gl.getShaderInfoLog(sh));
    gl.deleteShader(sh);
    return null;
  }
  return sh;
}

export class BubbleRenderer {
  private constructor(
    private readonly gl: WebGLRenderingContext,
    private readonly canvas: HTMLCanvasElement,
    private readonly program: WebGLProgram,
    private readonly loc: Record<string, WebGLUniformLocation | null>,
  ) {}

  static create(canvas: HTMLCanvasElement): BubbleRenderer | null {
    // The shader writes premultiplied circle-edge pixels so WebKit can safely resample the transparent canvas on non-Retina displays without a bright halo.
    const gl = (canvas.getContext('webgl', { alpha: true, premultipliedAlpha: true, antialias: true, depth: false })
      || canvas.getContext('experimental-webgl', { alpha: true, premultipliedAlpha: true })) as WebGLRenderingContext | null;
    if (!gl) return null;
    const vs = compile(gl, gl.VERTEX_SHADER, VERTEX_SRC);
    const fs = compile(gl, gl.FRAGMENT_SHADER, FRAGMENT_SRC);
    if (!vs || !fs) return null;
    const program = gl.createProgram();
    if (!program) return null;
    gl.attachShader(program, vs);
    gl.attachShader(program, fs);
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error('[bubble] program link failed:', gl.getProgramInfoLog(program));
      return null;
    }
    gl.useProgram(program);
    const buffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]), gl.STATIC_DRAW);
    const aPos = gl.getAttribLocation(program, 'aPos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);
    const names = ['uResolution', 'uCenter', 'uRadius', 'uBaseColor', 'uAccentColor',
      'uCapCenter', 'uCapHalfSeg', 'uCapRadius', 'uCapRot', 'uCapOpacity', 'uCapBlur'];
    const loc: Record<string, WebGLUniformLocation | null> = {};
    for (const n of names) loc[n] = gl.getUniformLocation(program, n);
    return new BubbleRenderer(gl, canvas, program, loc);
  }

  resize(sizeLogical: number, dpr: number): void {
    const px = Math.round(sizeLogical * dpr);
    this.canvas.width = px;
    this.canvas.height = px;
    this.canvas.style.width = `${sizeLogical}px`;
    this.canvas.style.height = `${sizeLogical}px`;
    this.gl.viewport(0, 0, px, px);
    this.gl.useProgram(this.program);
    this.gl.uniform2f(this.loc.uResolution, px, px);
    this.gl.uniform2f(this.loc.uCenter, px / 2, px / 2);
    this.gl.uniform1f(this.loc.uRadius, px / 2);
  }

  draw(baseSrgb: [number, number, number], accentSrgb: [number, number, number], caps: CapsuleUniforms): void {
    const gl = this.gl;
    gl.useProgram(this.program);
    gl.disable(gl.BLEND);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.uniform3f(this.loc.uBaseColor, baseSrgb[0], baseSrgb[1], baseSrgb[2]);
    gl.uniform3f(this.loc.uAccentColor, accentSrgb[0], accentSrgb[1], accentSrgb[2]);
    gl.uniform2fv(this.loc.uCapCenter, caps.center);
    gl.uniform1fv(this.loc.uCapHalfSeg, caps.halfSeg);
    gl.uniform1fv(this.loc.uCapRadius, caps.radius);
    gl.uniform1fv(this.loc.uCapRot, caps.rot);
    gl.uniform1fv(this.loc.uCapOpacity, caps.opacity);
    gl.uniform1fv(this.loc.uCapBlur, caps.blur);
    gl.drawArrays(gl.TRIANGLES, 0, 6);
  }

  dispose(): void {
    // Release the program without force-losing the context because React StrictMode reuses the same canvas during its setup-cleanup-setup cycle; a real unmount removes the canvas and allows context collection.
    this.gl.deleteProgram(this.program);
  }
}
