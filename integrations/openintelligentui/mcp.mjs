// MIT upstream skill/resource/assembler interface adapted to Open Learn.
// No user data, provider keys, executable server tools, or app mutations are exposed.
import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import {dirname,resolve} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createServer} from 'node:http';
const root=dirname(fileURLToPath(import.meta.url));
const require=createRequire(process.env.OPENLEARN_VISUAL_NODE_PACKAGE||resolve(root,'package.json'));
const load=name=>import(pathToFileURL(require.resolve(name)).href);
const {McpServer,ResourceTemplate}=await load('@modelcontextprotocol/sdk/server/mcp.js');
const {StdioServerTransport}=await load('@modelcontextprotocol/sdk/server/stdio.js');
const {StreamableHTTPServerTransport}=await load('@modelcontextprotocol/sdk/server/streamableHttp.js');
const {z}=await load('zod');
const names={'master-agent-playbook':'master-playbook','svg-diagram-skill':'svg-diagrams','agent-skills-vol2':'advanced-visualization'};
const styles=JSON.parse(readFileSync(resolve(root,'design-system.json'),'utf8'));
const skill=name=>{if(!Object.hasOwn(names,name))throw new Error('Unknown visual skill');return readFileSync(resolve(root,'upstream/apps/agent/skills',names[name],'SKILL.md'),'utf8');};
const escape=value=>value.replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
export function assembleDocument(html,title='Open Learn visual'){
  // The consumer must render this as sandboxed content. Arbitrary host messaging is deliberately absent.
  return `<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>${escape(title)}</title><meta http-equiv="Content-Security-Policy" content="default-src 'none';script-src 'unsafe-inline' 'unsafe-eval';style-src 'unsafe-inline';img-src data: blob:;connect-src 'none';form-action 'none';base-uri 'none'"><style>${Object.values(styles).join('\n')}</style></head><body>${html}</body></html>`;
}
export function createVisualMcpServer(){
  const server=new McpServer({name:'openlearn-visuals',version:'1.0.0'});
  server.registerResource('skills-list','skills://list',{mimeType:'application/json'},async()=>({contents:[{uri:'skills://list',mimeType:'application/json',text:JSON.stringify(Object.keys(names))}]}));
  server.registerResource('skill',new ResourceTemplate('skills://{name}',{list:async()=>({resources:Object.keys(names).map(name=>({uri:`skills://${name}`,name}))})}),{mimeType:'text/plain'},async(uri,{name})=>({contents:[{uri:uri.href,text:skill(name)}]}));
  for(const [prompt,name] of Object.entries({create_widget:'master-agent-playbook',create_svg_diagram:'svg-diagram-skill',create_visualization:'agent-skills-vol2'}))server.registerPrompt(prompt,{description:'Open Learn visual generation guidance'},async()=>({messages:[{role:'user',content:{type:'text',text:skill(name)}}]}));
  server.registerResource('design-guidance','visuals://design-guidance',{mimeType:'text/plain'},async()=>({contents:[{uri:'visuals://design-guidance',text:readFileSync(resolve(root,'design-skill.md'),'utf8')}]}));
  server.registerTool('assemble_document',{description:'Assemble a styled HTML visual. Returns text, not a displayed or deployed visual. Render in an isolated iframe with scripts only; no same-origin, navigation or host actions.',inputSchema:{title:z.string().max(160),description:z.string().max(1000),html:z.string().max(512000)}},async({html,title})=>({content:[{type:'text',text:assembleDocument(html,title)}]}));
  return server;
}
if(process.argv[1]&&resolve(process.argv[1])===fileURLToPath(import.meta.url)){
  if(!process.argv.includes('--http'))await createVisualMcpServer().connect(new StdioServerTransport());
  else{
    let active=0;
    createServer(async(req,res)=>{
      const port=Number(process.env.OPENLEARN_VISUAL_MCP_PORT||8142);
      if(!['127.0.0.1:'+port,'localhost:'+port].includes(req.headers.host)){res.writeHead(403).end();return;}
      if(req.headers.origin&&!['http://127.0.0.1:'+port,'http://localhost:'+port].includes(req.headers.origin)){res.writeHead(403).end();return;}
      if(req.url==='/health'){res.writeHead(200,{'content-type':'application/json'}).end('{"status":"ok"}');return;}
      if(req.url!=='/mcp'||req.method!=='POST'){res.writeHead(405).end();return;}
      if(active>=16){res.writeHead(503).end();return;}
      active++;const server=createVisualMcpServer();const transport=new StreamableHTTPServerTransport({sessionIdGenerator:undefined,enableJsonResponse:true});
      try{
        let size=0;const chunks=[];
        for await(const chunk of req){size+=chunk.length;if(size>600000)throw new Error('Input too large');chunks.push(chunk);}
        await server.connect(transport);await transport.handleRequest(req,res,JSON.parse(Buffer.concat(chunks).toString()));
      }catch{if(!res.headersSent)res.writeHead(400);res.end();}
      finally{await server.close();active--;}
    }).listen(Number(process.env.OPENLEARN_VISUAL_MCP_PORT||8142),'127.0.0.1',()=>console.error('Open Learn visual MCP: http://127.0.0.1:8142/mcp'));
  }
}
