import * as React from "react";
import { useMutation } from "@apollo/client";
import { toast } from "sonner";

import {
  PlaylistDetailDocument,
  UpdatePlaylistSettingsDocument,
} from "@/types/generated/graphql";
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

type Playlist = {
  id: string;
  name: string;
  description: string;
};

type Props = {
  playlist: Playlist;
  initialKnobs: {
    minSize: number;
    maxSize: number | null;
    tHigh: number;
    tLow: number;
    base: number;
    pFloor: number;
  };
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

function NumberField({
  id,
  label,
  value,
  onChange,
  step = 1,
  hint,
}: {
  id: string;
  label: string;
  value: number;
  onChange: (n: number) => void;
  step?: number;
  hint?: string;
}) {
  return (
    <div>
      <Label htmlFor={id} className="block mb-1">
        {label}
      </Label>
      <Input
        id={id}
        type="number"
        value={value}
        step={step}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {hint ? (
        <p className="mt-1 text-xs text-muted-foreground leading-snug">{hint}</p>
      ) : null}
    </div>
  );
}

export function EditSettingsDialog({
  playlist,
  initialKnobs,
  open,
  onOpenChange,
}: Props) {
  const [name, setName] = React.useState(playlist.name);
  const [description, setDescription] = React.useState(playlist.description);
  const [minSize, setMinSize] = React.useState(initialKnobs.minSize);
  const [maxSizeEnabled, setMaxSizeEnabled] = React.useState(
    initialKnobs.maxSize !== null,
  );
  const [maxSize, setMaxSize] = React.useState(initialKnobs.maxSize ?? 50);
  const [tHigh, setTHigh] = React.useState(initialKnobs.tHigh);
  const [tLow, setTLow] = React.useState(initialKnobs.tLow);
  const [base, setBase] = React.useState(initialKnobs.base);
  const [pFloor, setPFloor] = React.useState(initialKnobs.pFloor);

  const [update, { loading }] = useMutation(UpdatePlaylistSettingsDocument, {
    refetchQueries: [
      { query: PlaylistDetailDocument, variables: { id: playlist.id } },
    ],
  });

  // Seed every field from the current props when the dialog OPENS. The dialog
  // is always mounted and the parent passes fresh object literals each render,
  // so keying this on prop identity would wipe the user's edits on any parent
  // re-render. Keying on `open` snapshots fresh values per open and leaves the
  // form alone while editing.
  React.useEffect(() => {
    if (!open) return;
    setName(playlist.name);
    setDescription(playlist.description);
    setMinSize(initialKnobs.minSize);
    setMaxSizeEnabled(initialKnobs.maxSize !== null);
    setMaxSize(initialKnobs.maxSize ?? 50);
    setTHigh(initialKnobs.tHigh);
    setTLow(initialKnobs.tLow);
    setBase(initialKnobs.base);
    setPFloor(initialKnobs.pFloor);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    try {
      await update({
        variables: {
          id: playlist.id,
          name,
          description,
          engine: {
            minSize,
            maxSize: maxSizeEnabled ? maxSize : null,
            tHigh,
            tLow,
            base,
            pFloor,
          },
        },
      });
      toast.success("Settings saved.");
      onOpenChange(false);
    } catch {
      toast.error("Could not save settings.");
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <form onSubmit={handleSubmit}>
        <DialogHeader>
          <DialogTitle>Playlist settings</DialogTitle>
          <DialogDescription>
            Name, description, and selection-engine knobs.
          </DialogDescription>
        </DialogHeader>
        <DialogContent className="space-y-4 max-h-[70vh] overflow-y-auto">
          <div className="space-y-2">
            <Label htmlFor="es-name">Name</Label>
            <Input
              id="es-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="es-desc">Description</Label>
            <Input
              id="es-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>

          <details className="border rounded-md p-3">
            <summary className="cursor-pointer text-sm font-medium">
              Engine knobs
            </summary>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <NumberField
                id="minSize"
                label="Min size"
                value={minSize}
                onChange={setMinSize}
              />
              <div>
                <Label className="block mb-1">
                  <input
                    type="checkbox"
                    checked={maxSizeEnabled}
                    onChange={(e) => setMaxSizeEnabled(e.target.checked)}
                    className="mr-2"
                  />
                  Cap max size
                </Label>
                {maxSizeEnabled ? (
                  <Input
                    type="number"
                    value={maxSize}
                    onChange={(e) => setMaxSize(Number(e.target.value))}
                    min={1}
                  />
                ) : null}
              </div>
              <NumberField
                id="base"
                label="Base chance (net 0 votes)"
                value={base}
                onChange={setBase}
                step={0.05}
                hint={
                  "Probability a song is included when its votes are even " +
                  "(upvotes = downvotes). 0.5 = a coin flip. This is the " +
                  "starting point that upvotes raise and downvotes lower."
                }
              />
              <NumberField
                id="tHigh"
                label="Guaranteed at (net upvotes)"
                value={tHigh}
                onChange={setTHigh}
                hint={
                  "Net upvotes at which a song is always included (100%). " +
                  "Between 0 and here the chance ramps from the base up to " +
                  "certain — e.g. 5 means 5 net upvotes locks it in."
                }
              />
              <NumberField
                id="tLow"
                label="Floored at (net downvotes)"
                value={tLow}
                onChange={setTLow}
                hint={
                  "Net downvotes at which a song hits its minimum chance. " +
                  "Between 0 and here the chance ramps from the base down to " +
                  "the floor — e.g. 5 means 5 net downvotes bottoms it out."
                }
              />
              <NumberField
                id="pFloor"
                label="Minimum chance (floor)"
                value={pFloor}
                onChange={setPFloor}
                step={0.05}
                hint={
                  "The lowest a song's chance can drop. Above 0, even heavily " +
                  "downvoted songs keep a small chance of sneaking in; 0 means " +
                  "they can be excluded entirely."
                }
              />
            </div>
          </details>
        </DialogContent>
        <DialogFooter>
          <Button
            type="button"
            variant="ghost"
            onClick={() => onOpenChange(false)}
          >
            Cancel
          </Button>
          <Button type="submit" disabled={loading || !name.trim()}>
            {loading ? "Saving…" : "Save settings"}
          </Button>
        </DialogFooter>
      </form>
    </Dialog>
  );
}
