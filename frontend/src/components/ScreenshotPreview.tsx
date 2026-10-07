import { useState } from "react";

import { assetUrl } from "@/api/client";
import { Modal } from "@/components/ui/modal";

/** Thumbnail that opens the full-size screenshot in an accessible modal. */
export function ScreenshotPreview({ src, alt, caption, className }: { src: string | null; alt: string; caption?: string; className?: string }) {
  const [open, setOpen] = useState(false);
  const url = assetUrl(src);
  if (!url) return <p className="text-xs text-muted-foreground">No screenshot.</p>;
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className={`block w-full overflow-hidden rounded-lg border border-border ${className ?? ""}`} aria-label={`Enlarge screenshot: ${alt}`}>
        <img src={url} alt={alt} loading="lazy" className="w-full object-cover object-top" />
      </button>
      <Modal open={open} onClose={() => setOpen(false)} title={caption ?? alt} wide>
        <img src={url} alt={alt} className="mx-auto max-h-[75vh] w-auto rounded border border-border" />
        <p className="mt-3 text-center text-xs"><a className="text-primary hover:underline" href={url} target="_blank" rel="noreferrer">Open original in new tab</a></p>
      </Modal>
    </>
  );
}
