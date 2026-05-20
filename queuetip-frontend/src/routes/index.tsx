import { createFileRoute } from "@tanstack/react-router";

export const Route = createFileRoute("/")({
  component: () => (
    <div className="container py-12">
      <h1 className="text-3xl font-bold">Queuetip</h1>
      <p className="mt-2 text-muted-foreground">Frontend scaffold live.</p>
    </div>
  ),
});
