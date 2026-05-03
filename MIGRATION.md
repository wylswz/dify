# Graphon 0.3.0 Migration Guide

This document summarizes the breaking changes and migration steps when upgrading graphon to version 0.3.0.

## Breaking Changes

### 1. Node Constructor Parameter: `config` → `data`

The node constructor parameter has been renamed from `config` to `data` across all node types.

**Before:**
```python
node = AnswerNode(
    node_id="node-1",
    config=AnswerNodeData(...),
    graph_init_params=init_params,
    graph_runtime_state=runtime_state,
)
```

**After:**
```python
node = AnswerNode(
    node_id="node-1",
    data=AnswerNodeData(...),
    graph_init_params=init_params,
    graph_runtime_state=runtime_state,
)
```

**Affected Node Types:**
- AnswerNode
- StartNode
- EndNode
- HumanInputNode
- KnowledgeIndexNode
- TemplateTransformNode
- HttpRequestNode
- TriggerWebhookNode
- DatasourceNode
- ToolNode
- IterationNode
- TriggerEventNode
- All custom node implementations

**Migration Steps:**
1. Search for all node instantiations using `config=` parameter
2. Replace `config=` with `data=` in node constructors
3. Update test fixtures and mock node classes
4. Update any assertions checking constructor call arguments

### 2. ModelProviderFactory Constructor Changes

The `ModelProviderFactory` constructor signature has changed and no longer accepts the `model_runtime` parameter.

**Before:**
```python
factory = ModelProviderFactory(model_runtime=model_runtime)
```

**After**
```python
factory = ModelProviderFactory(runtime=model_runtime)
```



### 3. ModelProviderFactory API Changes

The `ModelProviderFactory` API has changed:

**Removed Method:**
- `get_model_type_instance()` - This method is no longer available

**Migration:**
Update code that uses `get_model_type_instance()` to use the new API (specifics depend on the graphon 0.3.0 documentation).

## Test Migration Checklist

### Node Tests
- [ ] Update `test_node_factory.py` - DummyNode constructor
- [ ] Update `test_knowledge_index_node.py` - helper function
- [ ] Update `test_template_transform_node.py` and spec
- [ ] Update `test_http_request_node.py`
- [ ] Update `test_webhook_node.py` and `test_webhook_file_conversion.py`
- [ ] Update `test_base_node.py`
- [ ] Update `test_answer.py`
- [ ] Update `test_datasource_node.py`
- [ ] Update `test_tool_node.py`
- [ ] Update `test_iteration_child_engine_errors.py`
- [ ] Update `test_trigger_event_node.py`
- [ ] Update `test_parallel_human_input_join_resume.py`
- [ ] Update `test_mock_factory.py`
- [ ] Update `test_mock_nodes.py`

### ModelProviderFactory Tests
- [ ] Update `test_model_provider_factory.py` - constructor calls
- [ ] Update `test_entities_provider_configuration.py` - mock expectations
- [ ] Update `test_model_runtime_factory.py` - mock expectations
- [ ] Update `test_provider_manager.py` - mock expectations
- [ ] Update `test_node.py` (llm) - ModelProviderFactory usage

## Known Issues

### DatasourceNode Constructor
The `DatasourceNode` constructor may have additional parameter changes beyond the `config` → `data` rename. Verify the full constructor signature in graphon 0.3.0.

### Test Mocking
Tests that mock `ModelProviderFactory` or use fake runtimes will need to be updated to work with the new factory pattern. Consider:
- Mocking `create_plugin_model_provider_factory` instead of `ModelProviderFactory`
- Using integration tests with real plugin runtime when possible
- Updating mock expectations to match the new API

## Verification

After migration, run the test suite to verify:
```bash
make test
```

Focus on:
- Node-related tests in `api/tests/unit_tests/core/workflow/nodes/`
- Model runtime tests in `api/tests/unit_tests/core/model_runtime/`
- Provider configuration tests in `api/tests/unit_tests/core/entities/`

## References

- Graphon 0.3.0 changelog (if available)
- Graphon repository documentation
- Related PRs or issues
