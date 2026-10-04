import { useState, type ReactNode } from "react";

import { familyColor } from "../../lib/colors";
import { fmtInt } from "../../lib/format";
import { ChainText } from "../icons";
import { Collapsible, Message } from "../ui";

/**
 * One collapsible section per family group, largest first. The largest is open unless the user
 * toggled it; a family the user opened or closed keeps that choice as the scope changes.
 */
export default function FamilySections<T extends { family: string }>({
  groups,
  count,
  children,
}: {
  groups: T[];
  count: (group: T) => number;
  children: (group: T) => ReactNode;
}) {
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  if (groups.length === 0) return <Message>No generation metadata in scope.</Message>;
  return (
    <>
      {groups.map((group, i) => (
        <Collapsible
          key={group.family}
          open={toggled[group.family] ?? i === 0}
          onToggle={(open) => setToggled((t) => ({ ...t, [group.family]: open }))}
          title={
            <span className="flex items-center gap-2">
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{
                  background: group.family === "all" ? "#a1a1aa" : familyColor(group.family),
                }}
              />
              <ChainText text={group.family} kind="pipeline" />
              <span className="font-normal text-zinc-500 tabular-nums">{fmtInt(count(group))}</span>
            </span>
          }
        >
          {children(group)}
        </Collapsible>
      ))}
    </>
  );
}
