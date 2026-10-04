export const VERTEX_SRC = `
attribute vec2 aPos;
void main() {
  gl_Position = vec4(aPos, 0.0, 1.0);
}
`;

export const FRAGMENT_SRC = `
precision highp float;
const int COUNT = 8;
uniform vec2 uResolution;
uniform vec2 uCenter;
uniform float uRadius;
uniform vec3 uBaseColor;   // sRGB 0..1
uniform vec3 uAccentColor; // sRGB 0..1
uniform vec2 uCapCenter[COUNT];
uniform float uCapHalfSeg[COUNT];
uniform float uCapRadius[COUNT];
uniform float uCapRot[COUNT];
uniform float uCapOpacity[COUNT];
uniform float uCapBlur[COUNT];

// Distance from a point to the capsule centerline segment along the local y axis, without subtracting the radius.
float distanceToSpine(vec2 p, float halfSeg) {
  p.y -= clamp(p.y, -halfSeg, halfSeg);
  return length(p);
}

float capsuleMask(vec2 point, float halfSeg, float radius, float antialiasWidth) {
  float signedDistance = distanceToSpine(point, halfSeg) - radius;
  return 1.0 - smoothstep(-antialiasWidth, antialiasWidth, signedDistance);
}

float blurredCapsuleCoverage(vec2 point, float halfSeg, float radius, float blurRadius) {
  // Equal-weight golden-angle samples drawn from a Gaussian distribution preserve energy without introducing a Cartesian lattice.
  float sigma = max(blurRadius, 0.5);
  float antialiasWidth = max(0.75, sigma * 0.25);
  float coverage = 0.0;
  for (int sampleIndex = 0; sampleIndex < 32; sampleIndex++) {
    float sequenceValue = (float(sampleIndex) + 0.5) / 32.0;
    float sampleRadius = sigma * sqrt(-2.0 * log(1.0 - sequenceValue));
    float sampleAngle = float(sampleIndex) * 2.39996322973;
    vec2 offset = vec2(cos(sampleAngle), sin(sampleAngle)) * sampleRadius;
    coverage += capsuleMask(point + offset, halfSeg, radius, antialiasWidth);
  }
  return coverage / 32.0;
}

vec3 softKnee(vec3 value, float knee, float ceiling) {
  vec3 compressed = knee + (ceiling - knee) * (1.0 - exp(-(value - knee) / (ceiling - knee)));
  return mix(value, compressed, step(knee, value));
}

// Weight in [0, 1] for saturated bases whose hue lies between magenta-red and yellow; exactly zero for other hues and for low-saturation bases so their rendering is unchanged.
float warmBaseWeight(vec3 color) {
  float maxChannel = max(color.r, max(color.g, color.b));
  float minChannel = min(color.r, min(color.g, color.b));
  float chroma = maxChannel - minChannel;
  if (chroma < 0.0001) return 0.0;
  float hue;
  if (maxChannel == color.r) {
    hue = mod((color.g - color.b) / chroma, 6.0);
  } else if (maxChannel == color.g) {
    hue = (color.b - color.r) / chroma + 2.0;
  } else {
    hue = (color.r - color.g) / chroma + 4.0;
  }
  hue *= 60.0;
  float hueWeight = hue < 180.0 ? 1.0 - smoothstep(60.0, 80.0, hue) : smoothstep(320.0, 340.0, hue);
  float saturationWeight = smoothstep(0.35, 0.55, chroma / maxChannel);
  return hueWeight * saturationWeight;
}

void main() {
  // y-down relative coordinate to match SwiftUI's coordinate space
  vec2 rel = vec2(gl_FragCoord.x - uCenter.x, (uResolution.y - gl_FragCoord.y) - uCenter.y);
  // Screen-blend directly in gamma/sRGB space to match Core Animation's SwiftUI screen compositing; linear-light blending under-brightens overlaps and suppresses the outer glow.
  vec3 result = uBaseColor;
  vec3 accent = uAccentColor;
  for (int i = 0; i < COUNT; i++) {
    vec2 local = rel - uCapCenter[i];
    float a = -uCapRot[i];
    float c = cos(a);
    float s = sin(a);
    vec2 lp = vec2(c * local.x - s * local.y, s * local.x + c * local.y);
    float coverage = blurredCapsuleCoverage(lp, uCapHalfSeg[i], uCapRadius[i], uCapBlur[i]);
    float alpha = coverage * uCapOpacity[i];
    vec3 screen = 1.0 - (1.0 - result) * (1.0 - accent);
    result = mix(result, screen, alpha);
  }
  vec3 uncompressed = result;
  // Compress dense overlaps along their existing color direction. A per-channel hard ceiling creates flat plateaus, especially when a saturated red channel reaches the limit before the others.
  vec3 singleScreen = 1.0 - (1.0 - uBaseColor) * (1.0 - uAccentColor);
  vec3 highlightRange = max(singleScreen - uBaseColor, vec3(0.0001));
  vec3 normalizedHighlight = max(result - uBaseColor, vec3(0.0)) / highlightRange;
  float highlightLevel = max(normalizedHighlight.r, max(normalizedHighlight.g, normalizedHighlight.b));
  if (highlightLevel > 0.55) {
    float compressedLevel = 0.55 + 0.17 * (1.0 - exp(-(highlightLevel - 0.55) / 0.17));
    result = uBaseColor + (result - uBaseColor) * (compressedLevel / highlightLevel);
  }
  // Saturated red-to-yellow bases already sit near the top of their red channel, so the shared compression is driven by green and blue and darkens dense cores as overlaps stack. For those bases only, compress each channel softly toward white so cores brighten monotonically and read whiter than the surrounding accent ring.
  float warmWeight = warmBaseWeight(uBaseColor);
  if (warmWeight > 0.0) {
    vec3 whiteHeadroom = max(1.0 - uBaseColor, vec3(0.0001));
    vec3 whiteHighlight = softKnee(max(uncompressed - uBaseColor, vec3(0.0)) / whiteHeadroom, 0.65, 0.92);
    result = mix(result, uBaseColor + whiteHeadroom * whiteHighlight, warmWeight);
  }
  float dist = length(rel);
  // Clip with an inward-only anti-alias band so coverage is zero at and beyond uRadius, preserving the native one-pixel circle edge. Premultiply the edge color because the canvas is composited and resampled with premultiplied alpha.
  float circleCoverage = 1.0 - smoothstep(uRadius - 1.0, uRadius, dist);
  gl_FragColor = vec4(result * circleCoverage, circleCoverage);
}
`;
