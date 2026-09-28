"use client";

import { createContext, useContext, type ReactNode } from "react";

const ReaderAuthContext = createContext(false);

export function ReaderAuthProvider({
  authenticated,
  children,
}: {
  authenticated: boolean;
  children: ReactNode;
}) {
  return <ReaderAuthContext.Provider value={authenticated}>{children}</ReaderAuthContext.Provider>;
}

export function useReaderAuthenticated(): boolean {
  return useContext(ReaderAuthContext);
}
