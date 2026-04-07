# O3DE Component Catalog

Quick reference of O3DE component names for use with `add_component`. Names must
match exactly — use these strings verbatim.

---

## Core

| Component | Purpose | Common Pairing |
|-----------|---------|----------------|
| `Transform` | Position, rotation, scale (auto-added) | Every entity |

## Rendering

| Component | Purpose | Common Pairing |
|-----------|---------|----------------|
| `Mesh` | 3D model rendering | + Material |
| `Material` | Surface appearance / shader | + Mesh |
| `Decal` | Projected texture on surfaces | Standalone |
| `SkinnedMesh` | Animated character mesh | + Actor, Anim Graph |

## Lighting

| Component | Purpose | Notes |
|-----------|---------|-------|
| `Directional Light` | Sun / global directional light | One per scene typically |
| `Point Light` | Omnidirectional light source | Local area lighting |
| `Spot Light` | Cone-shaped light | Flashlights, spotlights |
| `Area Light` | Rectangular/disk light | Soft area illumination |
| `HDRi Skybox` | Sky dome from HDR image | + Global Skylight (IBL) |
| `Global Skylight (IBL)` | Image-based ambient lighting | + HDRi Skybox |

## Physics (PhysX)

> **O3DE 2510+:** PhysX component names were changed. `PhysX Collider` →
> `PhysX Primitive Collider`, `PhysX Rigid Body` → `PhysX Dynamic Rigid Body`.
> Use the names below for O3DE 2510+. For older builds, use the legacy names.

| Component | Purpose | Behavior |
|-----------|---------|----------|
| `PhysX Primitive Collider` | Collision shape (box, sphere, capsule) | Static if alone, solid blocker |
| `PhysX Mesh Collider` | Collision shape from mesh geometry | For complex shapes |
| `PhysX Shape Collider` | Collision from Shape component | Uses attached Shape |
| `PhysX Dynamic Rigid Body` | Dynamic physics body | Requires a collider |
| `PhysX Static Rigid Body` | Optimized static body | For non-moving colliders |
| `PhysX Character Controller` | Player-style movement | Alternative to Rigid Body |
| `PhysX Force Region` | Applies force to entering bodies | e.g. wind, gravity wells |
| `PhysX Ball Joint` | Ball-and-socket constraint | Between two bodies |
| `PhysX Hinge Joint` | Single-axis rotation constraint | Doors, wheels |
| `PhysX Prismatic Joint` | Single-axis slide constraint | Pistons, sliders |

### Physics Behavior Quick Reference

| Desired Behavior | Components |
|------------------|------------|
| Static wall/floor | Mesh + PhysX Primitive Collider |
| Falling/movable object | Mesh + PhysX Primitive Collider + PhysX Dynamic Rigid Body |
| Trigger zone (invisible) | PhysX Primitive Collider (IsTrigger=True) |
| Kinematic platform | PhysX Primitive Collider + PhysX Dynamic Rigid Body (Kinematic=True) |
| Player character | Mesh + PhysX Character Controller |

## Scripting

| Component | Purpose | Notes |
|-----------|---------|-------|
| `Lua Script` | Lua behavior script | Attach .lua file |
| `Script Canvas` | Visual scripting graph | Attach .scriptcanvas file |
| `Comment` | Editor-only text annotation | No runtime effect |

## Camera

| Component | Purpose | Notes |
|-----------|---------|-------|
| `Camera` | View / projection | Set as active camera |

## Audio

| Component | Purpose | Notes |
|-----------|---------|-------|
| `Audio Trigger` | Play audio events | Wwise integration |
| `Audio Rtpc` | Real-time parameter control | Wwise parameter |
| `Audio Switch` | Audio state switch | Wwise switch |
| `Audio Environment` | Reverb / environment zone | Spatial audio |
| `Audio Proxy` | Audio emitter position | Auto-added with audio comps |

## Animation

| Component | Purpose | Notes |
|-----------|---------|-------|
| `Actor` | Character skeleton + skin | + SkinnedMesh |
| `Anim Graph` | Animation state machine | + Actor |
| `Simple Motion` | Single animation playback | + Actor |

## Terrain & Vegetation

| Component | Purpose | Notes |
|-----------|---------|-------|
| `Terrain Layer Spawner` | Defines terrain region | + Axis Aligned Box Shape |
| `Terrain Height Gradient List` | Height data for terrain | + Gradient components |
| `Terrain Surface Gradient List` | Surface material mapping | + Gradient components |
| `Vegetation Layer Spawner` | Places vegetation instances | + shape + filter comps |
| `Vegetation Asset List` | Vegetation prefab references | Used by layer spawner |

## Shapes

| Component | Purpose | Notes |
|-----------|---------|-------|
| `Axis Aligned Box Shape` | Box volume | Terrain, triggers |
| `Box Shape` | Oriented box volume | Triggers, volumes |
| `Sphere Shape` | Sphere volume | Triggers, volumes |
| `Capsule Shape` | Capsule volume | Character colliders |
| `Cylinder Shape` | Cylinder volume | General volumes |
| `Spline` | Curve path | Roads, rivers |

## UI

| Component | Purpose | Notes |
|-----------|---------|-------|
| `UI Canvas Ref` | Reference to UI canvas | HUD, menus |
| `UI Canvas Proxy Ref` | Dynamic UI canvas loader | Runtime UI |

## Networking

| Component | Purpose | Notes |
|-----------|---------|-------|
| `Net Binding` | Network replication | Multiplayer sync |
| `Network Transform` | Replicated transform | + Net Binding |

---

## Component Dependency Chains

Some components require others to be present. O3DE usually auto-adds
dependencies, but knowing them avoids confusion:

```
Mesh → Transform (auto)
PhysX Dynamic Rigid Body → PhysX Primitive Collider → Transform
PhysX Character Controller → Transform
Actor → Transform
Anim Graph → Actor
SkinnedMesh → Actor
Simple Motion → Actor
Vegetation Layer Spawner → Shape component (any)
Terrain Layer Spawner → Axis Aligned Box Shape
```

## Common Entity Templates

### Static Prop
```
Mesh + Material + PhysX Primitive Collider
```

### Dynamic Object
```
Mesh + Material + PhysX Primitive Collider + PhysX Dynamic Rigid Body
```

### Character
```
Actor + Anim Graph + SkinnedMesh + PhysX Character Controller
```

### Environment
```
HDRi Skybox + Global Skylight (IBL)
```

### Light
```
Directional Light    (sun)
Point Light          (lamp)
Spot Light           (flashlight)
```

### Trigger Zone
```
Box Shape + PhysX Primitive Collider (IsTrigger=True)
```
