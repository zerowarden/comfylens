import { useState, type ReactNode } from "react";

import { fmtInt } from "../../lib/format";
import { ChainText } from "../icons";
import { Collapsible, FamilyDot, Message } from "../ui";

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
  /** The count beside the family name; none draws no count, e.g. for a single selected image. */
  count?: (group: T) => number;
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
              <FamilyDot family={group.family} large />
              <ChainText text={group.family} kind="pipeline" />
              {count && (
                <span className="font-normal text-muted tabular-nums"> {fmtInt(count(group))}</span>
              )}
            </span>
          }
        >
          {children(group)}
        </Collapsible>
      ))}
    </>
  );
}
