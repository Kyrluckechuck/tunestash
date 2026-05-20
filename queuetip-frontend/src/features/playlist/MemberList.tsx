import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

type Member = {
  account: { id: string; displayName: string };
  role: string;
};

type Props = {
  members: Member[];
  currentAccountId: string;
  isOwner?: boolean;
  onKick?: (accountId: string, displayName: string) => void;
  onPromote?: (accountId: string, displayName: string) => void;
};

export function MemberList({
  members,
  currentAccountId,
  isOwner = false,
  onKick,
  onPromote,
}: Props) {
  return (
    <ul className="space-y-1">
      {members.map((m) => (
        <li
          key={m.account.id}
          className="flex items-center justify-between text-sm gap-2"
        >
          <span className="truncate">
            {m.account.displayName}
            {m.account.id === currentAccountId ? " (you)" : ""}
          </span>
          <div className="flex items-center gap-1 shrink-0">
            <Badge variant={m.role === "owner" ? "default" : "secondary"}>
              {m.role}
            </Badge>
            {isOwner && m.account.id !== currentAccountId ? (
              <>
                {m.role !== "owner" && onPromote ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-xs"
                    onClick={() =>
                      onPromote(m.account.id, m.account.displayName)
                    }
                  >
                    Promote
                  </Button>
                ) : null}
                {onKick ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-6 px-2 text-xs text-destructive hover:text-destructive"
                    onClick={() => onKick(m.account.id, m.account.displayName)}
                  >
                    Kick
                  </Button>
                ) : null}
              </>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  );
}
