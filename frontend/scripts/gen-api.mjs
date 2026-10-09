#!/usr/bin/env node
/**
 * Generates the frontend API types from the backend's OpenAPI document.
 *
 * Why a hand-rolled generator instead of `openapi-typescript`: this project
 * runs TypeScript 7 (the native compiler), whose `typescript` package no longer
 * exposes the compiler API (`ts.factory`) that openapi-typescript requires (it
 * pins its peer to `typescript@^5.x`). The schemas we publish are simple enough
 * to map directly, so this script is dependency-free and fails loudly instead of
 * drifting silently.
 *
 * One deliberate reading: OpenAPI marks a field optional when pydantic gives it
 * a default, but the backend *serializes every field of a response model every
 * time*. The frontend only reads responses, so fields here are emitted as always
 * present; only fields that genuinely model `None` become `| null`.
 *
 * Regenerate whenever the backend changes:
 *
 *   node scripts/gen-api.mjs
 *   ROVER_API_URL=http://host:8000/openapi.json npm run gen:api
 */

import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(here, "../src/types/api.ts");
const URL = process.env.ROVER_API_URL ?? "http://localhost:8000/openapi.json";

/** Types the frontend maps to friendly aliases. If any disappears from the API,
 * generation fails instead of silently dropping a type. */
const REQUIRED = [
  "CameraStatus",
  "ChargeState",
  "ConnectionState",
  "Detection",
  "DetectionSnapshot",
  "FollowRequest",
  "FollowStatus",
  "HealthResponse",
  "Keypoint",
  "ModelDescription",
  "ModelsReport",
  "MotionRequest",
  "Pose",
  "PosePerson",
  "PoseSnapshot",
  "RoverStatus",
  "TelemetrySnapshot",
];

function refName(schema) {
  if (!schema.$ref) return null;
  const name = schema.$ref.split("/").pop();
  if (!name) throw new Error(`Unresolvable $ref: ${schema.$ref}`);
  return name;
}

function isNullable(schema) {
  return Array.isArray(schema.anyOf) && schema.anyOf.some((part) => part.type === "null");
}

function tsType(schema, schemas, stack) {
  if (!schema) return "unknown";
  const name = refName(schema);
  if (name) return name;
  if (schema.anyOf) {
    const parts = schema.anyOf
      .filter((part) => part.type !== "null")
      .map((part) => tsType(part, schemas, stack));
    const unique = [...new Set(parts)];
    return unique.join(" | ");
  }
  if (schema.type === "array") {
    const item = tsType(schema.items, schemas, stack);
    return item.includes("|") ? `(${item})[]` : `${item}[]`;
  }
  if (schema.type === "object" || schema.properties) {
    return objectType(schema, schemas, stack);
  }
  if (schema.type === "string") {
    if (Array.isArray(schema.enum) && schema.enum.length > 0) {
      const values = schema.enum.map((value) => JSON.stringify(value));
      return [...new Set(values)].join(" | ");
    }
    return "string";
  }
  if (schema.type === "integer" || schema.type === "number") return "number";
  if (schema.type === "boolean") return "boolean";
  if (schema.type === "null") return "null";
  return "unknown";
}

function objectType(schema, schemas, stack) {
  const entries = Object.entries(schema.properties ?? {});
  const lines = entries.map(([key, prop]) => {
    let fieldType = tsType(prop, schemas, stack);
    if (isNullable(prop) && !fieldType.includes("null")) fieldType += " | null";
    return `  ${key}: ${fieldType};`;
  });
  return lines.length > 0 ? `{\n${lines.join("\n")}\n}` : "Record<string, never>";
}

function schemaDeclaration(name, schema, schemas) {
  // Enums arrive as a plain string union.
  if (!schema.$ref && schema.type === "string" && Array.isArray(schema.enum)) {
    return `export type ${name} = ${tsType(schema, schemas, new Set())};`;
  }
  if (schema.$ref) {
    const target = refName(schema);
    return `export type ${name} = ${target};`;
  }
  if (schema.type === "object" || schema.properties) {
    return `export interface ${name} ${objectType(schema, schemas, new Set())}`;
  }
  return `export type ${name} = ${tsType(schema, schemas, new Set())};`;
}

function render(schemas) {
  const names = Object.keys(schemas).sort();
  const body = names
    .map((name) => schemaDeclaration(name, schemas[name], schemas))
    .join("\n\n");
  const header = [
    "/**",
    " * Generated from the backend's OpenAPI document — do not edit by hand.",
    " * Regenerate with `npm run gen:api` whenever the backend API changes.",
    " */",
    "",
    "",
  ].join("\n");
  return header + body + "\n";
}

async function main() {
  const response = await fetch(URL);
  if (!response.ok) {
    throw new Error(
      `OpenAPI ${URL} answered HTTP ${response.status}. Start the backend (simulator mode is enough) and retry.`,
    );
  }
  const document = await response.json();
  const schemas = document.components?.schemas ?? {};
  if (Object.keys(schemas).length === 0) {
    throw new Error("The OpenAPI document has no components.schemas; is this the right server?");
  }
  for (const name of REQUIRED) {
    if (!schemas[name]) {
      throw new Error(
        `Expected schema '${name}' is missing from the API (have ${Object.keys(schemas).join(", ")}).`,
      );
    }
  }
  writeFileSync(OUT, render(schemas), "utf8");
  console.log(`generated ${OUT} (${Object.keys(schemas).length} schemas)`);
}

main().catch((error) => {
  console.error(`gen:api failed: ${error.message}`);
  process.exit(1);
});