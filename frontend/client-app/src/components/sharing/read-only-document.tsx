import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";

function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Documents are stored as editor HTML; plain-text/markdown bodies are shown line by line.
export function toEditorHtml(content: string): string {
  if (/<[a-z][\s\S]*>/i.test(content)) return content;
  return content
    .split(/\r?\n/)
    .map((line) => `<p>${escapeHtml(line)}</p>`)
    .join("");
}

/** Renders document content through the editor schema (no raw HTML injection), never editable. */
export function ReadOnlyDocument({ content }: { content: string }) {
  const editor = useEditor(
    {
      extensions: [StarterKit],
      content: toEditorHtml(content),
      editable: false,
      editorProps: {
        attributes: {
          class: "prose prose-sm sm:prose max-w-none focus:outline-none",
          "aria-readonly": "true",
          "data-testid": "read-only-document",
        },
      },
    },
    [content]
  );

  return <EditorContent editor={editor} />;
}
