import * as React from "react";
import { useMutation } from "@apollo/client";
import { useRouter } from "@tanstack/react-router";
import { toast } from "sonner";

import { CreatePlaylistDocument, MyPlaylistsDocument } from "@/types/generated/graphql";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type Props = { open: boolean; onOpenChange: (open: boolean) => void };

export function NewPlaylistDialog({ open, onOpenChange }: Props) {
  const router = useRouter();
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [createPlaylist, { loading }] = useMutation(CreatePlaylistDocument, {
    refetchQueries: [{ query: MyPlaylistsDocument }],
  });

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      const result = await createPlaylist({
        variables: { name: name.trim(), description: description.trim() || null },
      });
      const id = result.data?.createPlaylist.id;
      onOpenChange(false);
      setName("");
      setDescription("");
      toast.success("Playlist created.");
      if (id) {
        await router.navigate({ to: "/playlists/$id", params: { id } });
      }
    } catch {
      toast.error("Could not create playlist.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <form onSubmit={handleSubmit}>
        <DialogHeader>
          <DialogTitle>New playlist</DialogTitle>
          <DialogDescription>
            Name it; you&apos;ll get a share link for your friends.
          </DialogDescription>
        </DialogHeader>
        <DialogContent className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="np-name">Name</Label>
            <Input
              id="np-name"
              value={name}
              required
              onChange={(e) => setName(e.target.value)}
              autoFocus
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="np-description">Description (optional)</Label>
            <Input
              id="np-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
        </DialogContent>
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button type="submit" disabled={loading || !name.trim()}>
            {loading ? "Creating..." : "Create playlist"}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}
