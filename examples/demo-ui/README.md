# Kaori Protocol — Demo UI

This directory contains the reference demo UI for the Kaori Protocol.

## Overview

A React-based frontend demonstrating the Kaori observation and truth verification workflow.

## Getting Started

```bash
cd examples/demo-ui
npm install
npm run dev
```

## Features

- Observation submission
- Truth state visualization
- Probe lifecycle display
- Vote interface

## Note

This is a demo application and NOT part of the open-core packages. Production UIs should import from the open-core packages:

```javascript
// Production code imports from packages
import { TruthState, Observation } from 'kaori-truth';
```
