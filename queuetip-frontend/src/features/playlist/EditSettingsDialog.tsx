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
}: {
  id: string;
  label: string;
  value: number;
  onChange: (n: number) => void;
  step?: number;
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

  React.useEffect(() => {
    setName(playlist.name);
    setDescription(playlist.description);
  }, [playlist]);

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
                id="tHigh"
                label="t_high (guaranteed-from)"
                value={tHigh}
                onChange={setTHigh}
              />
              <NumberField
                id="tLow"
                label="t_low (floor-at)"
                value={tLow}
                onChange={setTLow}
              />
              <NumberField
                id="base"
                label="base (p at net=0)"
                value={base}
                onChange={setBase}
                step={0.05}
              />
              <NumberField
                id="pFloor"
                label="p_floor"
                value={pFloor}
                onChange={setPFloor}
                step={0.05}
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
