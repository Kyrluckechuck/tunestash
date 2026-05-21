import { CheckCircle2, ExternalLink } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

type Props = {
  message: string;
  next?: string;
  onReset: () => void;
};

/**
 * Shown after `requestMagicLink` succeeds — same card for sign-in and sign-up
 * because both paths produce the same "check your email" outcome.
 */
export function MagicLinkSuccess({ message, next, onReset }: Props) {
  return (
    <div className="container max-w-md py-16">
      <Card>
        <CardHeader>
          <CheckCircle2 className="h-10 w-10 text-green-600" />
          <CardTitle>Check your email</CardTitle>
          <CardDescription>{message}</CardDescription>
        </CardHeader>
        <CardFooter className="flex flex-col items-start gap-3">
          {next ? (
            <p className="text-sm text-muted-foreground flex items-center gap-1">
              <ExternalLink className="h-3 w-3 shrink-0" />
              After signing in, return to:{" "}
              <a href={next} className="underline hover:text-foreground break-all">
                {next}
              </a>
            </p>
          ) : null}
          <Button variant="ghost" onClick={onReset}>
            Use a different email
          </Button>
        </CardFooter>
      </Card>
    </div>
  );
}
