"use client";
import { createContext, useContext } from 'react';
export type SandboxFunction = { name: string; handler: (args: unknown) => Promise<unknown> };
export const SandboxFunctions = createContext<SandboxFunction[]>([]);
export const useSandboxFunctions = () => useContext(SandboxFunctions);
