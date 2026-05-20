import * as React from "react";
import { useMutation } from "@apollo/client";
import { useRouter } from "@tanstack/react-router";
import { toast } from "sonner";

import { CreateExportDocument } from "@/types/generated/graphql";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type Props = {
  playlistId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export function CreateExportDialog({ playlistId, open, onOpenChange }: Props) {
  const router = useRouter();
  const [excludeMyDownvotes, setExcludeMyDownvotes] = React.useState(false);
  const [createExport, { loading }] = useMutation(CreateExportDocument);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      const { data } = await createExport({
        variables: {
          playlistId,
          options: { excludeMyDownvotes },
        },
      });
      const id = data?.createExport.id;
      if (!id) {
        toast.error("Export failed.");
        return;
      }
      onOpenChange(false);
      await router.navigate({ to: "/exports/$id", params: { id } });
    } catch {
      toast.error("Could not create export.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <form onSubmit={handleSubmit}>
        <DialogHeader>
          <DialogTitle>Create export</DialogTitle>
          <DialogDescription>
            Roll a fresh tracklist from this playlist&apos;s contributions and votes.
          </DialogDescription>
        </DialogHeader>
        <DialogContent>
          <div className="flex items-center gap-3">
            <Switch
              id="exclude-downvotes"
              checked={excludeMyDownvotes}
              onCheckedChange={setExcludeMyDownvotes}
            />
            <Label htmlFor="exclude-downvotes" className="cursor-pointer">
              Exclude songs I downvoted
            </Label>
          </div>
        </DialogContent>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" disabled={loading}>
            {loading ? "Rolling…" : "Create export"}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}
