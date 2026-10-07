import { Globe, ImageOff } from "lucide-react";

import { Card, CardHeader } from "@/components/ui/card";

export function BrowserPreview({ src, url }: { src: string | null; url: string }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader title="Browser preview" />
      <div className="flex items-center gap-2 border-b border-border bg-background/50 px-3 py-1.5 text-xs text-muted-foreground">
        <Globe className="h-3.5 w-3.5" /> <span className="truncate">{url}</span>
      </div>
      <div className="grid aspect-[16/10] place-items-center bg-black/30">
        {src ? (
          <img src={src} alt="Latest screenshot of the page under test" className="h-full w-full object-contain object-top" />
        ) : (
          <div className="flex flex-col items-center gap-2 text-xs text-muted-foreground">
            <ImageOff className="h-6 w-6" /> No screenshot yet
          </div>
        )}
      </div>
    </Card>
  );
}
