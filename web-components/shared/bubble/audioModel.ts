export type AudioEventType = 'none' | 'transient' | 'sustained' | 'decay' | 'attack';
export type BubbleAnimationMode = 'ambient' | 'audioResponsive' | 'processing';

function nowSeconds(): number {
  return (typeof performance !== 'undefined' ? performance.now() : Date.now()) / 1000;
}

export class AudioSpring {
  currentValue = 0;
  private targetValue = 0;
  private velocity = 0;
  stiffness = 300;
  damping = 30;
  mass = 1;

  update(target: number, deltaTime: number): void {
    this.targetValue = target;
    const displacement = this.currentValue - this.targetValue;
    const springForce = -this.stiffness * displacement;
    const dampingForce = -this.damping * this.velocity;
    const acceleration = (springForce + dampingForce) / this.mass;
    this.velocity += acceleration * deltaTime;
    this.currentValue += this.velocity * deltaTime;
    if (Math.abs(displacement) < 0.001 && Math.abs(this.velocity) < 0.001) {
      this.currentValue = this.targetValue;
      this.velocity = 0;
    }
  }

  adaptToAudioCharacteristics(
    bassLevel: number,
    trebleLevel: number,
    audioEvent: AudioEventType,
    audioVelocity: number,
  ): void {
    let newStiffness = 200;
    let newDamping = 25;
    let newMass = 1;
    newMass += bassLevel * 2.0;
    newStiffness -= bassLevel * 50.0;
    newMass = Math.max(0.1, newMass - trebleLevel * 0.5);
    newStiffness += trebleLevel * 100.0;
    switch (audioEvent) {
      case 'transient': newStiffness += 150; newDamping += 10; break;
      case 'sustained': newDamping += 20; newStiffness -= 50; break;
      case 'attack': newStiffness += 100; break;
      case 'decay': newDamping += 30; break;
      case 'none': newDamping += 15; break;
    }
    newStiffness += Math.abs(audioVelocity) * 100.0;
    this.stiffness = this.stiffness * 0.6 + newStiffness * 0.4;
    this.damping = this.damping * 0.6 + newDamping * 0.4;
    this.mass = this.mass * 0.7 + newMass * 0.3;
    this.stiffness = Math.max(50, Math.min(800, this.stiffness));
    this.damping = Math.max(5, Math.min(100, this.damping));
    this.mass = Math.max(0.1, Math.min(5, this.mass));
  }
}

export class BubbleAudioModel {
  currentLevel = 0;
  bassLevel = 0;
  midLevel = 0;
  trebleLevel = 0;
  audioVelocity = 0;
  audioEventType: AudioEventType = 'none';

  springLevel = 0;
  springOpacity = 0;
  springSize = 0;
  springBlur = 0;

  currentAnimationMode: BubbleAnimationMode = 'ambient';
  private targetAnimationMode: BubbleAnimationMode = 'ambient';
  modeTransitionProgress = 1;
  private readonly modeTransitionSpeed = 3.0;

  private smoothedLevel = 0;
  private previousRawLevel = 0;
  private levelHistory: number[] = [];
  private previousEventDetectionTime = 0;
  private stepAccumulator = 0;

  private readonly historySize = 5;
  private readonly eventCooldown = 0.1;
  private readonly baseSmoothingFactor = 0.08;
  private readonly adaptiveSmoothingFactor = 0.25;
  private readonly maxLevelJump = 0.15;
  private readonly noiseThreshold = 0.008;

  private readonly levelSpring = new AudioSpring();
  private readonly opacitySpring = new AudioSpring();
  private readonly sizeSpring = new AudioSpring();
  private readonly blurSpring = new AudioSpring();

  get targetMode(): BubbleAnimationMode {
    return this.targetAnimationMode;
  }

  setAnimationMode(newMode: BubbleAnimationMode): void {
    if (newMode !== this.targetAnimationMode) {
      this.targetAnimationMode = newMode;
      this.modeTransitionProgress = 0;
    }
  }

  ingestAudioLevel(rawLevel: number): void {
    this.analyzeAudioFrequencies(rawLevel);
    this.calculateAudioVelocity(rawLevel);
    this.detectAudioEvents(rawLevel);
    this.smoothedLevel = this.applyAdvancedSmoothing(rawLevel);
    this.currentLevel = this.smoothedLevel;
  }

  advance(realDeltaSeconds: number): void {
    this.stepAccumulator += realDeltaSeconds;
    while (this.stepAccumulator >= 0.03) {
      this.updateModeTransition(0.03);
      this.updateSpringPhysics(0.03);
      this.stepAccumulator -= 0.03;
    }
  }

  private analyzeAudioFrequencies(rawLevel: number): void {
    const levelChange = Math.abs(rawLevel - this.previousRawLevel);
    const bassTarget = rawLevel * 0.8 + (rawLevel > 0.3 ? 0.2 : 0.0);
    this.bassLevel = this.bassLevel * 0.85 + bassTarget * 0.15;
    const midTarget = rawLevel * 0.9;
    this.midLevel = this.midLevel * 0.75 + midTarget * 0.25;
    const trebleTarget = Math.min(1.0, levelChange * 3.0 + rawLevel * 0.3);
    this.trebleLevel = this.trebleLevel * 0.6 + trebleTarget * 0.4;
  }

  private calculateAudioVelocity(rawLevel: number): void {
    this.levelHistory.push(rawLevel);
    if (this.levelHistory.length > this.historySize) {
      this.levelHistory.shift();
    }
    if (this.levelHistory.length >= 2) {
      const recentChange =
        this.levelHistory[this.levelHistory.length - 1] -
        this.levelHistory[this.levelHistory.length - 2];
      const smoothedVelocity = this.audioVelocity * 0.7 + recentChange * 0.3;
      this.audioVelocity = Math.max(-1.0, Math.min(1.0, smoothedVelocity));
    }
  }

  private detectAudioEvents(rawLevel: number): void {
    const t = nowSeconds();
    if (t - this.previousEventDetectionTime <= this.eventCooldown) return;
    const levelChange = rawLevel - this.previousRawLevel;
    const velocityMagnitude = Math.abs(this.audioVelocity);
    if (velocityMagnitude > 0.3 && levelChange > 0.15) {
      this.audioEventType = 'transient';
      this.previousEventDetectionTime = t;
    } else if (rawLevel > 0.4 && velocityMagnitude < 0.1) {
      this.audioEventType = 'sustained';
      this.previousEventDetectionTime = t;
    } else if (levelChange < -0.1 && rawLevel < this.previousRawLevel) {
      this.audioEventType = 'decay';
      this.previousEventDetectionTime = t;
    } else if (velocityMagnitude > 0.2 && levelChange > 0.05) {
      this.audioEventType = 'attack';
      this.previousEventDetectionTime = t;
    } else if (velocityMagnitude < 0.05 && rawLevel < 0.1) {
      this.audioEventType = 'none';
    }
  }

  private applyAdvancedSmoothing(rawLevel: number): number {
    const levelDifference = rawLevel - this.previousRawLevel;
    let clampedLevel: number;
    if (Math.abs(levelDifference) > this.maxLevelJump) {
      const direction = levelDifference > 0 ? 1.0 : -1.0;
      clampedLevel = this.previousRawLevel + this.maxLevelJump * direction;
    } else {
      clampedLevel = rawLevel;
    }
    let filteredLevel: number;
    if (Math.abs(clampedLevel - this.smoothedLevel) < this.noiseThreshold) {
      filteredLevel = this.smoothedLevel;
    } else {
      filteredLevel = clampedLevel;
    }
    const changeMagnitude = Math.abs(filteredLevel - this.smoothedLevel);
    const dynamicSmoothingFactor =
      changeMagnitude > 0.1 ? this.adaptiveSmoothingFactor : this.baseSmoothingFactor;
    const newSmoothedLevel =
      dynamicSmoothingFactor * filteredLevel + (1 - dynamicSmoothingFactor) * this.smoothedLevel;
    this.previousRawLevel = rawLevel;
    return newSmoothedLevel;
  }

  private updateModeTransition(deltaTime: number): void {
    if (this.modeTransitionProgress < 1) {
      this.modeTransitionProgress = Math.min(
        1,
        this.modeTransitionProgress + this.modeTransitionSpeed * deltaTime,
      );
      if (this.modeTransitionProgress >= 1) {
        this.currentAnimationMode = this.targetAnimationMode;
      }
    }
  }

  private updateSpringPhysics(deltaTime: number): void {
    for (const spring of [this.levelSpring, this.opacitySpring, this.sizeSpring, this.blurSpring]) {
      spring.adaptToAudioCharacteristics(
        this.bassLevel, this.trebleLevel, this.audioEventType, this.audioVelocity,
      );
    }
    this.levelSpring.update(this.smoothedLevel, deltaTime);
    this.opacitySpring.update(this.smoothedLevel * 2.0, deltaTime);
    this.sizeSpring.update(this.smoothedLevel * 1.5, deltaTime);
    this.blurSpring.update(this.trebleLevel * 2.5, deltaTime);
    this.springLevel = this.levelSpring.currentValue;
    this.springOpacity = this.opacitySpring.currentValue;
    this.springSize = this.sizeSpring.currentValue;
    this.springBlur = this.blurSpring.currentValue;
  }
}
