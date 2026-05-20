import { Badge } from "@/components/ui/badge";

type Member = {
  account: { id: string; displayName: string };
  role: string;
};

type Props = { members: Member[]; currentAccountId: string };

export function MemberList({ members, currentAccountId }: Props) {
  return (
    <ul className="space-y-1">
      {members.map((m) => (
        <li key={m.account.id} className="flex items-center justify-between text-sm">
          <span>
            {m.account.displayName}
            {m.account.id === currentAccountId ? " (you)" : ""}
          </span>
          <Badge variant={m.role === "owner" ? "default" : "secondary"}>{m.role}</Badge>
        </li>
      ))}
    </ul>
  );
}
