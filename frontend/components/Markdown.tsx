"use client";

import { memo, useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { copyText, haptic } from "@/lib/api";
import { IconCheck, IconCopy } from "./icons";

function textOf(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textOf).join("");
  if (node && typeof node === "object" && "props" in node) {
    return textOf((node as { props: { children?: ReactNode } }).props.children);
  }
  return "";
}

function CodeBlock({ children }: { children?: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const child = Array.isArray(children) ? children[0] : children;
  const cls = (child as { props?: { className?: string } })?.props?.className ?? "";
  const lang = /language-(\w+)/.exec(cls)?.[1] ?? "code";
  const code = textOf(children).replace(/\n$/, "");
  return (
    <div className="my-3 overflow-hidden rounded-2xl border border-white/8 bg-[#0d0d14]">
      <div className="flex items-center justify-between border-b border-white/6 px-3.5 py-1.5">
        <span className="font-mono text-[12px] text-fg-3">{lang}</span>
        <button
          onClick={async () => { if (await copyText(code)) { haptic(); setCopied(true); setTimeout(() => setCopied(false), 1600); } }}
          className="tap -mr-2 flex items-center gap-1.5 rounded-lg px-2 text-[12px] text-fg-2"
          aria-label="Code kopieren"
        >
          {copied ? <IconCheck size={15} /> : <IconCopy size={15} />}
          {copied ? "Kopiert" : "Kopieren"}
        </button>
      </div>
      <pre className="scroll-smooth-ios overflow-x-auto p-3.5 font-mono text-[13px] leading-relaxed">{children}</pre>
    </div>
  );
}

export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: true, ignoreMissing: true }]]}
        components={{
          pre: ({ children }) => <CodeBlock>{children}</CodeBlock>,
          a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});
