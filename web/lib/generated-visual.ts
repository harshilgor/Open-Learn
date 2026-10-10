import { z } from 'zod';
import { parseVisualization } from './visualization-spec';

const contentSchema = z.object({
  initialHeight: z.number().finite().min(50).max(4000).optional(),
  generating: z.boolean().optional(), css: z.string().max(512000).optional(), cssComplete: z.boolean().optional(),
  html: z.array(z.string()).max(5000).optional(), htmlComplete: z.boolean().optional(),
  jsFunctions: z.string().max(512000).optional(), jsFunctionsComplete: z.boolean().optional(),
  jsExpressions: z.array(z.string()).max(5000).optional(), jsExpressionsComplete: z.boolean().optional(),
}).strict();
const tableSchema = z.object({title:z.string().max(300), columns:z.array(z.string().max(200)).min(1).max(12),
  rows:z.array(z.array(z.string().max(2000)).max(12)).max(200),source:z.string().trim().min(1).max(1000)})
  .refine(table=>table.rows.every(row=>row.length===table.columns.length));
const base = z.object({version:z.literal(2),type:z.literal('generated_ui'),id:z.string().regex(/^[A-Za-z0-9_-]+$/).max(120),
  revision:z.number().int().positive(),title:z.string().min(1).max(160),sourceLessonId:z.string().nullish().transform(value=>value||undefined),
  blockIndex:z.number().int().min(0).max(20).default(0),afterParagraph:z.number().int().min(0).max(20).default(0)});
const controlSchema=z.object({id:z.string().regex(/^[A-Za-z][A-Za-z0-9_-]{0,63}$/),label:z.string().min(1).max(120),minimum:z.number().finite(),maximum:z.number().finite(),initial:z.number().finite()})
  .refine(value=>value.minimum<value.maximum&&value.initial>=value.minimum&&value.initial<=value.maximum);
const generatedBase=base.extend({controls:z.array(controlSchema).max(8).default([]),controlValues:z.record(z.number().finite()).default({})});
export const generatedVisualSchema = z.discriminatedUnion('renderer',[
  generatedBase.extend({renderer:z.literal('open_generative_ui'),content:contentSchema}),
  generatedBase.extend({renderer:z.literal('a2ui'),content:tableSchema}),
]).refine(value=>JSON.stringify(value.content).length<=512000&&Object.entries(value.controlValues).every(([id,number])=>{const control=value.controls.find(value=>value.id===id);return control&&number>=control.minimum&&number<=control.maximum;}));
export type GeneratedVisual = z.infer<typeof generatedVisualSchema>;
export const generatedVisualRefSchema = base.extend({type:z.literal('generated_ui_ref'), runId:z.string().max(160)});
export type GeneratedVisualRef = z.infer<typeof generatedVisualRefSchema>;
export function parseGeneratedVisualRef(value:unknown):GeneratedVisualRef|null {
  const parsed=generatedVisualRefSchema.safeParse(value);return parsed.success?parsed.data:null;
}
export function parseGeneratedVisual(value:unknown):GeneratedVisual|null{
  const parsed=generatedVisualSchema.safeParse(value);return parsed.success?parsed.data:null;
}
export function parseVisualArtifact(value:unknown){return parseGeneratedVisualRef(value)||parseGeneratedVisual(value)||parseVisualization(value);}
export const VISUAL_PROMPT_DRAFT = 'openlearn:visual-prompt-draft';
