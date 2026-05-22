import type { CodegenConfig } from "@graphql-codegen/cli";

const config: CodegenConfig = {
  schema: "./src/types/generated/queuetip-schema.graphql",
  documents: ["./src/queries/**/*.graphql"],
  generates: {
    "./src/types/generated/": {
      preset: "client",
      presetConfig: { fragmentMasking: false },
    },
  },
};
export default config;
