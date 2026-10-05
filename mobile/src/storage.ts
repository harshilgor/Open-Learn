import {openDatabaseAsync} from 'expo-sqlite';
import type {JsonStore} from './protocol';
const db=openDatabaseAsync('openlearn-journals.db').then(async database=>{await database.execAsync('PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; CREATE TABLE IF NOT EXISTS journals (key TEXT PRIMARY KEY, payload TEXT NOT NULL);');return database;});
export const journals:JsonStore={
  async read<T>(key:string){const row=await (await db).getFirstAsync<{payload:string}>('SELECT payload FROM journals WHERE key=?',key);return row?JSON.parse(row.payload) as T:null;},
  async write(key,value){await (await db).runAsync('INSERT INTO journals(key,payload) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET payload=excluded.payload',key,JSON.stringify(value));},
};
