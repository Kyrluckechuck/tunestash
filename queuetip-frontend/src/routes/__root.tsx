import { createRootRoute } from "@tanstack/react-router";
import { Layout } from "@/components/Layout";

function NotFound() {
  return (
    <div className="container max-w-md py-16">
      <h1 className="text-2xl font-bold mb-2">Page not found</h1>
      <p className="text-muted-foreground">
        The page you&apos;re looking for doesn&apos;t exist.
      </p>
    </div>
  );
}

export const Route = createRootRoute({
  component: Layout,
  notFoundComponent: NotFound,
});
