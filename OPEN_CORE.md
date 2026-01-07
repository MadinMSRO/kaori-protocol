# Open Core Definition

Kaori Protocol follows a strict Open Core architecture to balance community transparency with sustainable development.

## 1. Open Source (Apache 2.0)
The repository root and `packages/` directory constitute the Open Source Proving Ground.

### Included Packages:
- **`kaori-truth`**: The pure, deterministic compiler for TruthStates. This is the heart of the protocol.
- **`kaori-flow`**: The physics of Trust and Standing.
- **`kaori-spec`**: All Protocol Specifications (TRUTH_SPEC, FLOW_SPEC) and ClaimType schemas.
- **`kaori-db`**: Standard database schemas and migrations.
- **`kaori-api`**: Reference implementation of the Orchestrator and API.

## 2. Proprietary / Enterprise Extensions
Proprietary extensions are NOT included in this repository. These typically include:
- High-performance, multi-region consensus engines.
- Advanced anti-sybil detection systems using proprietary datasets.
- Enterprise-grade SLA connectors.
- SaaS orchestration UI.

## 3. Compatibility
All proprietary extensions MUST be fully compatible with the Open Source `kaori-spec`. The Open Source `kaori-truth` compiler is the reference implementation for correctness.
