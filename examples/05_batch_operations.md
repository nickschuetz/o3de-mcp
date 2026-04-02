# Example 5: Batch Operations

Techniques for efficient bulk operations that minimize tool calls and token
usage. Use these patterns when creating or modifying many entities at once.

## Batch Create Entities

Instead of N `create_entity` calls, use one `run_editor_python`:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.bus as bus\nimport azlmbr.math as math\nimport azlmbr.components as comp\nimport json\n\nparent = azlmbr.entity.EntityId()\nentities = [\n    {'name': 'Tree_01', 'pos': (10, 5, 0)},\n    {'name': 'Tree_02', 'pos': (15, -3, 0)},\n    {'name': 'Tree_03', 'pos': (20, 8, 0)},\n    {'name': 'Rock_01', 'pos': (12, 0, 0)},\n    {'name': 'Rock_02', 'pos': (18, -5, 0)},\n]\nresults = []\nfor e in entities:\n    eid = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', parent)\n    editor.EditorEntityAPIBus(bus.Event, 'SetName', eid, e['name'])\n    comp.TransformBus(bus.Event, 'SetWorldTranslation', eid, azlmbr.math.Vector3(*e['pos']))\n    results.append({'name': e['name'], 'id': str(eid)})\nprint(json.dumps(results))"
  }
}
```

**Cost: 1 tool call instead of 5.**

## Batch Add Components

Add the same component set to multiple entities by name pattern:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.bus as bus\nimport azlmbr.entity as entity\n\nsearch = entity.SearchFilter()\nsearch.names = ['Tree_*']\nids = entity.SearchBus(bus.Broadcast, 'SearchEntities', search)\n\nmesh_t = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['Mesh'], entity.EntityType().Game)\nmat_t = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['Material'], entity.EntityType().Game)\ncol_t = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['PhysX Collider'], entity.EntityType().Game)\n\nfor eid in ids:\n    editor.EditorComponentAPIBus(bus.Event, 'AddComponentsOfType', eid, mesh_t + mat_t + col_t)\n\nprint(f'Added Mesh+Material+Collider to {len(ids)} Tree entities')"
  }
}
```

**Cost: 1 tool call instead of 3 * N.**

## Batch Set Properties

Set a property across all matching entities:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.bus as bus\nimport azlmbr.entity as entity\nimport azlmbr.components as comp\nimport azlmbr.math as math\n\nsearch = entity.SearchFilter()\nsearch.names = ['Rock_*']\nids = entity.SearchBus(bus.Broadcast, 'SearchEntities', search)\n\nfor eid in ids:\n    comp.TransformBus(bus.Event, 'SetLocalScale', eid, math.Vector3(2.0, 2.0, 2.0))\n\nprint(f'Scaled {len(ids)} Rock entities to 2x')"
  }
}
```

## Batch Create with Components

The most efficient pattern — create entities and add components in one call:

```json
{
  "tool": "run_editor_python",
  "arguments": {
    "script": "import azlmbr.editor as editor\nimport azlmbr.bus as bus\nimport azlmbr.entity as entity\nimport azlmbr.components as comp\nimport azlmbr.math as math\nimport json\n\n# Pre-resolve component type IDs once\nmesh_t = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['Mesh'], entity.EntityType().Game)\ncol_t = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['PhysX Collider'], entity.EntityType().Game)\nrb_t = editor.EditorComponentAPIBus(bus.Broadcast, 'FindComponentTypeIdsByEntityType', ['PhysX Rigid Body'], entity.EntityType().Game)\nall_types = mesh_t + col_t + rb_t\n\nparent = azlmbr.entity.EntityId()\nitems = [\n    {'name': 'Barrel_01', 'pos': (3, 0, 5)},\n    {'name': 'Barrel_02', 'pos': (5, 2, 5)},\n    {'name': 'Barrel_03', 'pos': (4, -1, 8)},\n    {'name': 'Barrel_04', 'pos': (6, 3, 6)},\n    {'name': 'Barrel_05', 'pos': (2, -3, 7)},\n]\nresults = []\nfor item in items:\n    eid = editor.ToolsApplicationRequestBus(bus.Broadcast, 'CreateNewEntity', parent)\n    editor.EditorEntityAPIBus(bus.Event, 'SetName', eid, item['name'])\n    comp.TransformBus(bus.Event, 'SetWorldTranslation', eid, math.Vector3(*item['pos']))\n    editor.EditorComponentAPIBus(bus.Event, 'AddComponentsOfType', eid, all_types)\n    results.append({'name': item['name'], 'id': str(eid)})\n\nprint(json.dumps(results))"
  }
}
```

**Cost: 1 tool call creates 5 fully-configured physics objects.**

With individual tool calls this would be:
- 5 `create_entity` + 15 `add_component` + 5 `run_editor_python` (transforms) = **25 calls**

## Efficiency Comparison

| Approach | Entities | Tool Calls | Relative Cost |
|----------|----------|------------|---------------|
| Individual calls | 5 | 25 | 100% |
| Batch create + individual components | 5 | 6 | 24% |
| Fully batched | 5 | 1 | 4% |
| Fully batched | 20 | 1 | 1% |

## When to Use Each Approach

| Scenario | Recommended Approach |
|----------|---------------------|
| 1-2 entities, simple components | Individual tool calls |
| 3+ similar entities | Batch `run_editor_python` |
| Adding same components to many entities | Batch by name pattern search |
| Complex scene setup | Single comprehensive script |
| Debugging / exploring | Individual calls for clarity |
