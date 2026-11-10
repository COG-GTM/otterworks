import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";

function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Editor-saved documents are HTML (they start with a tag); anything else is shown as escaped text, line by line.
export function toEditorHtml(content: string, contentType?: string): string {
  if (contentType === "text/html" || /^\s*<[a-z][\w-]*[\s/>]/i.test(content)) return content;
  return content
    .split(/\r?\n/)
    .map((line) => `<p>${escapeHtml(line)}</p>`)
    .join("");
}

/** Renders document content through the editor schema (no raw HTML injection), never editable. */
export function ReadOnlyDocument({ content, contentType }: { content: string; contentType?: string }) {
  const editor = useEditor(
    {
      extensions: [StarterKit],
      content: toEditorHtml(content, contentType),
      editable: false,
      editorProps: {
        attributes: {
          class: "prose prose-sm sm:prose max-w-none focus:outline-none",
          "aria-readonly": "true",
          "data-testid": "read-only-document",
        },
      },
    },
    [content, contentType]
  );

  return <EditorContent editor={editor} />;
}
