"use client";

import { RelativeTime } from "@/components/relative-time";
import { fetchReaderAccount, type ReaderAccount } from "@/lib/auth/account";
import { loginPath } from "@/lib/auth/return-to";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";

type CommentAuthor = {
  username: string;
  avatar_url: string | null;
};

type PublicComment = {
  id: string;
  body: string;
  created_at: string;
  anonymous: boolean;
  author: CommentAuthor | null;
  replies?: PublicComment[];
};

const EMPTY_ACCOUNT: ReaderAccount = {
  authenticated: false,
  email: null,
  email_verified: null,
  locality_step: null,
  locality: null,
  username: null,
  avatar_url: null,
};

function errorText(status: number, detail: string): string {
  if (status === 401) return "Entrá para comentar.";
  if (detail === "email_not_verified") return "Verificá el correo para comentar.";
  if (detail === "username_required") return "Cargá un nombre de usuario en el perfil para comentar.";
  if (detail === "reply_not_root") return "Solo se puede responder a un comentario.";
  if (detail === "comment_invalid") return "El comentario no puede estar vacío ni pasar de 1000 caracteres.";
  if (detail === "rate_limited") return "Esperá un momento antes de publicar otro.";
  if (status === 404) return "Esta nota no acepta comentarios.";
  return "No se pudo publicar el comentario.";
}

function AuthorLine({ comment }: { comment: PublicComment }) {
  if (comment.anonymous || !comment.author) {
    return <span className="font-sans text-sm text-muted">Anónimo</span>;
  }
  return (
    <span className="flex items-center gap-2">
      {comment.author.avatar_url ? (
        <img
          src={comment.author.avatar_url}
          alt=""
          width={28}
          height={28}
          className="h-7 w-7 rounded-full object-cover"
        />
      ) : (
        <span className="h-7 w-7 rounded-full bg-surface-secondary" aria-hidden />
      )}
      <span className="font-sans text-sm text-primary">{comment.author.username}</span>
    </span>
  );
}

function CommentForm({
  slug,
  parentId,
  onPublished,
  onCancel,
}: {
  slug: string;
  parentId?: string;
  onPublished: () => void;
  onCancel?: () => void;
}) {
  const [body, setBody] = useState("");
  const [anonymous, setAnonymous] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      const response = await fetch(`/api/v1/articles/${encodeURIComponent(slug)}/comments`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          body,
          anonymous,
          parent_id: parentId ?? null,
        }),
      });
      if (!response.ok) {
        let detail = "";
        try {
          const payload = (await response.json()) as { detail?: unknown };
          detail = typeof payload.detail === "string" ? payload.detail : "";
        } catch {
          detail = "";
        }
        setError(errorText(response.status, detail));
        return;
      }
      setBody("");
      setAnonymous(false);
      onPublished();
    } catch {
      setError("No se pudo publicar el comentario.");
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="space-y-3">
      <label className="block font-sans text-sm text-secondary" htmlFor={parentId ? `reply-${parentId}` : "comment-body"}>
        {parentId ? "Respuesta" : "Comentario"}
        <textarea
          id={parentId ? `reply-${parentId}` : "comment-body"}
          value={body}
          onChange={(event) => setBody(event.target.value)}
          required
          maxLength={1000}
          rows={3}
          className="sl-input mt-1 min-h-24 w-full"
        />
      </label>
      <label className="flex items-center gap-2 font-sans text-sm text-secondary">
        <input
          type="checkbox"
          checked={anonymous}
          onChange={(event) => setAnonymous(event.target.checked)}
        />
        Publicar como anónimo
      </label>
      {error ? (
        <p role="alert" className="font-sans text-sm text-accent-ochre">
          {error}
        </p>
      ) : null}
      <div className="flex items-center gap-3">
        <button type="submit" disabled={pending} className="sl-btn-primary disabled:opacity-60">
          {pending ? "Publicando…" : parentId ? "Responder" : "Publicar"}
        </button>
        {onCancel ? (
          <button type="button" onClick={onCancel} className="font-sans text-sm text-secondary underline">
            Cancelar
          </button>
        ) : null}
      </div>
    </form>
  );
}

function CommentItem({
  comment,
  slug,
  canReply,
  onPublished,
}: {
  comment: PublicComment;
  slug: string;
  canReply: boolean;
  onPublished: () => void;
}) {
  const [replying, setReplying] = useState(false);
  return (
    <li className="space-y-3">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <AuthorLine comment={comment} />
          <span className="font-sans text-xs text-muted">
            <RelativeTime iso={comment.created_at} />
          </span>
        </div>
        <p className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-primary">{comment.body}</p>
        {canReply ? (
          <button
            type="button"
            onClick={() => setReplying((open) => !open)}
            className="font-sans text-sm text-secondary underline"
          >
            Responder
          </button>
        ) : null}
      </div>
      {replying ? (
        <CommentForm
          slug={slug}
          parentId={comment.id}
          onCancel={() => setReplying(false)}
          onPublished={() => {
            setReplying(false);
            onPublished();
          }}
        />
      ) : null}
      {comment.replies && comment.replies.length > 0 ? (
        <ul className="space-y-4 border-l border-border pl-4">
          {comment.replies.map((reply) => (
            <li key={reply.id} className="space-y-1">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <AuthorLine comment={reply} />
                <span className="font-sans text-xs text-muted">
                  <RelativeTime iso={reply.created_at} />
                </span>
              </div>
              <p className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-primary">{reply.body}</p>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

export function ArticleComments({ slug, returnTo }: { slug: string; returnTo: string }) {
  const [items, setItems] = useState<PublicComment[]>([]);
  const [account, setAccount] = useState<ReaderAccount>(EMPTY_ACCOUNT);
  const [ready, setReady] = useState(false);

  const load = useCallback(() => {
    return fetch(`/api/v1/articles/${encodeURIComponent(slug)}/comments`, { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) return [] as PublicComment[];
        const body = (await response.json()) as { items?: PublicComment[] };
        return Array.isArray(body.items) ? body.items : [];
      })
      .catch(() => [] as PublicComment[]);
  }, [slug]);

  useEffect(() => {
    let active = true;
    void Promise.all([load(), fetchReaderAccount()])
      .then(([comments, reader]) => {
        if (!active) return;
        setItems(comments);
        setAccount(reader);
      })
      .finally(() => {
        if (active) setReady(true);
      });
    return () => {
      active = false;
    };
  }, [load]);

  const canPost = account.authenticated && account.email_verified === true && Boolean(account.username);

  return (
    <section className="mt-10 space-y-4" aria-labelledby="comentarios">
      <h2 id="comentarios" className="font-heading text-lg text-primary">
        Comentarios
      </h2>
      {!ready ? <div className="h-16 animate-pulse bg-surface" /> : null}
      {ready && items.length === 0 ? (
        <p className="font-sans text-sm text-secondary">Todavía no hay comentarios.</p>
      ) : null}
      {items.length > 0 ? (
        <ul className="space-y-5">
          {items.map((comment) => (
            <CommentItem
              key={comment.id}
              comment={comment}
              slug={slug}
              canReply={canPost}
              onPublished={() => {
                void load().then(setItems);
              }}
            />
          ))}
        </ul>
      ) : null}
      {ready && !account.authenticated ? (
        <p className="font-sans text-sm text-secondary">
          <Link href={loginPath(returnTo)} className="underline">
            Entrá
          </Link>{" "}
          para comentar o responder.
        </p>
      ) : null}
      {ready && account.authenticated && account.email_verified !== true ? (
        <p className="font-sans text-sm text-secondary">
          <Link href="/perfil" className="underline">
            Verificá el correo
          </Link>{" "}
          para comentar.
        </p>
      ) : null}
      {ready && account.authenticated && account.email_verified === true && !account.username ? (
        <p className="font-sans text-sm text-secondary">
          <Link href="/perfil" className="underline">
            Cargá un nombre de usuario
          </Link>{" "}
          para comentar.
        </p>
      ) : null}
      {ready && canPost ? (
        <CommentForm
          slug={slug}
          onPublished={() => {
            void load().then(setItems);
          }}
        />
      ) : null}
    </section>
  );
}
