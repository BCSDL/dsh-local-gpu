import z from '@deepseek-ai/schemastery';
import {defineTool} from '@deepseek-ai/dsh-tools';
import {spawn} from 'node:child_process';
import {homedir} from 'node:os';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
export const name='local-gpu';
export const inject=['tools'];
export const Config=z.object({pythonExecutable:z.string().default(''),comfyDirectory:z.string().default(''),port:z.number().min(1024).max(65534).default(8188)});
export function apply(ctx,config){
 const root=join(homedir(),'.local-ai-tools','comfyui');let child;
 async function status(){try{const r=await fetch(`http://127.0.0.1:${config.port}/health`,{signal:AbortSignal.timeout(2000)});const value=await r.json();if(value.app!=='dsh-local-gpu')throw Error('Port belongs to another app');return value;}catch{return {ready:false,port:config.port};}}
 async function start(){const current=await status();if(current.ready)return current;if(child&&!child.killed)return {starting:true,port:config.port};
  child=spawn(config.pythonExecutable||join(root,'venv','Scripts','python.exe'),[fileURLToPath(new URL('../backend/bridge.py',import.meta.url)),'--port',String(config.port),'--comfy',config.comfyDirectory||join(root,'ComfyUI-0.39.0')],{stdio:['ignore','ignore','pipe'],windowsHide:true});
  child.on('error',err=>{console.error('[local-gpu] '+err.message);child=undefined;});child.on('exit',()=>{child=undefined;});child.stderr.on('data',chunk=>console.error('[local-gpu] '+chunk.toString().trim()));return {starting:true,port:config.port};}
 ctx.effect(()=>ctx.tools.register(defineTool({name:'local_image_runtime',description:'Start or inspect the optional local ComfyUI GPU-sharing runtime. Call start before generate_image/edit_image with the comfyui provider. Releases Gemma only during an approved local image job, refuses during active classroom processing, and terminates its own image inference process afterward.',parameters:{operation:{type:'string',required:true}},output:{schema:{type:'string'},render:(_args,value)=>[{type:'text',text:value}]},async execute(args){if(args.operation==='status')return JSON.stringify(await status());if(args.operation==='start')return JSON.stringify(await start());throw Error('Use start or status');}})),'local GPU runtime tool');
 ctx.on('dispose',()=>{if(child)child.kill();});
 // Only the lightweight loopback bridge starts here; no CUDA/model is loaded.
 void start();
}
