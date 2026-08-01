"use client"

import {
  ReactFlow,
  useNodesState,
  useEdgesState,
  type Edge,
  type NodeTypes,
} from "@xyflow/react"
import "@xyflow/react/dist/style.css"

import MigrationNode, {
  NODE_HEIGHT,
  NODE_WIDTH,
  type MigrationNode as MigrationNodeType,
  type MigrationNodeVariant,
} from "./migration-node"
import "./execution-flow.css"

const nodeTypes = {
  migration: MigrationNode,
} satisfies NodeTypes

/** Horizontal journey across ~1200px composed width. */
const GRAPH_W = 1200
const RAIL_Y = 160

function xFor(variant: MigrationNodeVariant, centerX: number) {
  return centerX - NODE_WIDTH[variant] / 2
}

function yFor(variant: MigrationNodeVariant, railCenterY: number) {
  return railCenterY - NODE_HEIGHT[variant] / 2
}

/**
 * Major stage centers — Shadow sits as the widest/central moment.
 * SQL · Analyze · Prediction · Shadow · Verify · Memory
 */
const STAGE = {
  sql: 90,
  analyze: 290,
  prediction: 500,
  shadow: 740,
  verify: 980,
  memory: 1160,
} as const

const initialNodes: MigrationNodeType[] = [
  {
    id: "sql",
    type: "migration",
    position: {
      x: xFor("sql", STAGE.sql),
      y: yFor("sql", RAIL_Y),
    },
    data: { variant: "sql" },
  },
  {
    id: "analyze",
    type: "migration",
    position: {
      x: xFor("analyze", STAGE.analyze),
      y: yFor("analyze", RAIL_Y + 12),
    },
    data: { variant: "analyze" },
  },
  {
    id: "prediction",
    type: "migration",
    position: {
      x: xFor("prediction", STAGE.prediction),
      y: yFor("prediction", RAIL_Y),
    },
    data: { variant: "prediction", feedbackTarget: true },
  },
  {
    id: "shadow",
    type: "migration",
    position: {
      x: xFor("shadow", STAGE.shadow),
      y: yFor("shadow", RAIL_Y),
    },
    data: { variant: "shadow" },
  },
  {
    id: "verify",
    type: "migration",
    position: {
      x: xFor("verify", STAGE.verify),
      y: yFor("verify", RAIL_Y),
    },
    data: { variant: "verify" },
  },
  {
    id: "memory",
    type: "migration",
    position: {
      x: xFor("memory", STAGE.memory),
      y: yFor("memory", RAIL_Y),
    },
    data: { variant: "memory", feedbackSource: true },
  },
]

const stroke = "rgba(255,255,255,0.2)"
const strokeQuiet = "rgba(255,255,255,0.14)"

const initialEdges: Edge[] = [
  {
    id: "e-sql-analyze",
    source: "sql",
    target: "analyze",
    type: "smoothstep",
    style: { stroke, strokeWidth: 1.15 },
  },
  {
    id: "e-analyze-prediction",
    source: "analyze",
    target: "prediction",
    type: "smoothstep",
    style: { stroke, strokeWidth: 1.15 },
  },
  {
    id: "e-prediction-shadow",
    source: "prediction",
    target: "shadow",
    type: "smoothstep",
    style: { stroke, strokeWidth: 1.25 },
  },
  {
    id: "e-shadow-verify",
    source: "shadow",
    target: "verify",
    type: "smoothstep",
    style: { stroke, strokeWidth: 1.15 },
  },
  {
    id: "e-verify-memory",
    source: "verify",
    target: "memory",
    type: "smoothstep",
    style: { stroke: strokeQuiet, strokeWidth: 1 },
  },
  {
    id: "e-memory-prediction",
    source: "memory",
    target: "prediction",
    sourceHandle: "fb",
    targetHandle: "fb",
    type: "default",
    style: {
      stroke: "rgba(139,126,200,0.4)",
      strokeWidth: 1,
      strokeDasharray: "4 6",
    },
  },
]

/**
 * Horizontal Migration Oracle journey — infrastructure composition, not a flowchart tree.
 */
export function ExecutionFlow() {
  const [nodes, , onNodesChange] = useNodesState(initialNodes)
  const [edges, , onEdgesChange] = useEdgesState(initialEdges)

  return (
    <div
      className="oracle-execution-flow w-full overflow-hidden"
      style={{ height: 360 }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        defaultViewport={{ x: 12, y: 28, zoom: 1 }}
        proOptions={{ hideAttribution: true }}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnDrag={false}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        preventScrolling={false}
        minZoom={1}
        maxZoom={1}
        defaultEdgeOptions={{
          type: "smoothstep",
          style: { stroke, strokeWidth: 1.15 },
        }}
        className="!bg-transparent"
        style={{ width: GRAPH_W + 40, maxWidth: "100%" }}
      />
    </div>
  )
}

export default ExecutionFlow
