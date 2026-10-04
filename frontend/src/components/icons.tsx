import arrowLeft from "@iconify-icons/lucide/arrow-left";
import arrowRight from "@iconify-icons/lucide/arrow-right";
import check from "@iconify-icons/lucide/check";
import chevronRight from "@iconify-icons/lucide/chevron-right";
import circleAlert from "@iconify-icons/lucide/circle-alert";
import copy from "@iconify-icons/lucide/copy";
import link from "@iconify-icons/lucide/link";
import x from "@iconify-icons/lucide/x";
// The offline build renders bundled icon data and never fetches from the Iconify API.
import { Icon, type IconifyIcon } from "@iconify/react/offline";
import { Fragment } from "react";

import { CHAIN_SEPARATOR, type ChainKind } from "../lib/chains";

const ICONS = {
  arrowLeft,
  arrowRight,
  check,
  chevronRight,
  circleAlert,
  copy,
  link,
  x,
} satisfies Record<string, IconifyIcon>;

export type IconName = keyof typeof ICONS;

export function Glyph({
  name,
  className = "",
  label,
}: {
  name: IconName;
  className?: string;
  /** Accessible name; decorative icons are hidden from assistive technology. */
  label?: string;
}) {
  return (
    <Icon
      icon={ICONS[name]}
      className={`inline-block shrink-0 ${className}`}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? "img" : undefined}
    />
  );
}

/** A chain key with its separators redrawn: "+" between pipeline stages, a link between LoRAs. */
export function ChainText({ text, kind }: { text: string; kind: ChainKind }) {
  const parts = text.split(CHAIN_SEPARATOR);
  if (parts.length === 1) return <>{text}</>;
  return (
    <>
      {parts.map((part, i) => (
        <Fragment key={i}>
          {i > 0 &&
            (kind === "lora" ? (
              <Glyph
                name="link"
                label="then"
                className="mx-1 size-3 align-[-0.125em] text-zinc-500"
              />
            ) : (
              <span className="text-zinc-500"> + </span>
            ))}
          {part}
        </Fragment>
      ))}
    </>
  );
}
