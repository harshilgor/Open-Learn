import test from 'node:test';
import assert from 'node:assert/strict';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {InMemoryTransport} from '@modelcontextprotocol/sdk/inMemory.js';
import {createVisualMcpServer} from './mcp.mjs';

test('MCP exposes upstream skill prompts and isolated document assembly',async()=>{
  const server=createVisualMcpServer();const client=new Client({name:'acceptance',version:'1'});
  const [host,remote]=InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(host),client.connect(remote)]);
  try{
    const resources=await client.listResources();assert(resources.resources.some(value=>value.uri==='skills://list'));
    const skills=await client.readResource({uri:'skills://list'});assert.equal(JSON.parse(skills.contents[0].text).length,3);
    const prompt=await client.getPrompt({name:'create_widget'});assert(prompt.messages[0].content.text.length>1000);
    const tools=await client.listTools();assert.deepEqual(tools.tools.map(value=>value.name),['assemble_document']);
    const result=await client.callTool({name:'assemble_document',arguments:{title:'Force',description:'Example',html:'<p>F = ma</p>'}});
    assert(result.content[0].text.includes("connect-src 'none'"));assert(result.content[0].text.includes('--color-background-primary'));
    const denied=await client.readResource({uri:'skills://..'}).then(()=>false,()=>true);assert(denied);
  }finally{await client.close();await server.close();}
});
