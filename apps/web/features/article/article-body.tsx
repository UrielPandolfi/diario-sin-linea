export function ArticleBody({ body }: { body: string }) {
  const paragraphs = body
    .split(/\n{2,}/)
    .map((part) => part.trim())
    .filter(Boolean);

  if (paragraphs.length === 0) return null;

  return (
    <div className="mt-6 space-y-4">
      {paragraphs.map((paragraph, index) => (
        <p key={index} className="font-sans text-[17px] leading-[1.65] text-primary">
          {paragraph}
        </p>
      ))}
    </div>
  );
}
