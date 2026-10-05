package openlearn.capture

import android.app.Service
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Intent
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import android.os.IBinder
import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.json.JSONObject
import org.json.JSONArray

class CaptureService : Service() {
  override fun onBind(intent: Intent?): IBinder? = null
  override fun onStartCommand(intent: Intent?,flags:Int,startId:Int):Int {
    if(intent?.action=="STOP") { Capture.finish("stopped");stopSelf();return START_NOT_STICKY }
    val manager=getSystemService(NOTIFICATION_SERVICE) as NotificationManager
    if(Build.VERSION.SDK_INT>=26) manager.createNotificationChannel(NotificationChannel("lecture", "Lecture recording",NotificationManager.IMPORTANCE_LOW))
    val stop=PendingIntent.getService(this,0,Intent(this,CaptureService::class.java).setAction("STOP"),PendingIntent.FLAG_IMMUTABLE)
    val builder=if(Build.VERSION.SDK_INT>=26) Notification.Builder(this,"lecture") else Notification.Builder(this)
    startForeground(7,builder.setContentTitle("Open Learn is recording").setContentText("Audio is saved on this device").setSmallIcon(android.R.drawable.ic_btn_speak_now).addAction(android.R.drawable.ic_media_pause,"Stop",stop).setOngoing(true).build())
    Capture.begin {stopForeground(STOP_FOREGROUND_REMOVE);stopSelf()}
    return START_NOT_STICKY
  }
  override fun onDestroy(){Capture.finish("interrupted");super.onDestroy()}
}

object Capture {
  private var folder:File?=null
  private var journal=JSONObject()
  @Volatile private var running=false
  private var thread:Thread?=null
  private var recorder:AudioRecord?=null
  private var output:RandomAccessFile?=null
  private var active:File?=null
  private var start=0L
  private var size=0
  private const val rate=16000
  private fun persist(){
    val directory=folder?:return
    val temporary=File(directory,"capture.tmp")
    RandomAccessFile(temporary,"rw").use {it.setLength(0);it.write(journal.toString().toByteArray());it.fd.sync()}
    check(temporary.renameTo(File(directory,"capture.json"))) {"Unable to save recording journal"}
  }
  @Synchronized fun prepare(directory:File,id:String){
    check(!running && journal.optString("status")!="paused") {"Stop the active recording first"}
    require(Regex("rec_[a-f0-9]{32}").matches(id))
    directory.mkdirs();check(!File(directory,"capture.json").exists())
    folder=directory
    journal=JSONObject().put("recordingId",id).put("directory",android.net.Uri.fromFile(directory).toString()).put("status","recording").put("startedAtMs",System.currentTimeMillis()).put("durationMs",0).put("interrupted",false).put("segments",JSONArray())
    persist()
  }
  @Synchronized fun snapshot():Map<String,Any?> = jsonMap(journal)
  private fun jsonMap(value:JSONObject):Map<String,Any?> = value.keys().asSequence().associateWith {key ->
    when(val v=value.get(key)){is JSONObject->jsonMap(v);is JSONArray->(0 until v.length()).map{val x=v.get(it);if(x is JSONObject)jsonMap(x) else x};JSONObject.NULL->null;else->v}
  }
  @Synchronized fun resume(){check(journal.optString("status")=="paused");journal.put("status","recording").put("interrupted",true);persist()}
  @Synchronized private fun openSegment(){
    val seq=journal.getJSONArray("segments").length()
    active=File(folder,"active_$seq.wav");output=RandomAccessFile(active,"rw");output!!.setLength(0);output!!.write(ByteArray(44));size=0
    start=System.currentTimeMillis()-journal.getLong("startedAtMs")
    journal.put("activeStartMs",start);persist()
  }
  private fun header(file:RandomAccessFile,length:Int){
    val h=ByteBuffer.allocate(44).order(ByteOrder.LITTLE_ENDIAN)
    h.put("RIFF".toByteArray()).putInt(length+36).put("WAVEfmt ".toByteArray()).putInt(16).putShort(1).putShort(1).putInt(rate).putInt(rate*2).putShort(2).putShort(16).put("data".toByteArray()).putInt(length)
    file.seek(0);file.write(h.array());file.fd.sync()
  }
  @Synchronized private fun seal(){
    val file=output?:return
    header(file,size);file.close();output=null
    if(size==0){active?.delete();return}
    val segments=journal.getJSONArray("segments");val destination=File(folder,"segment_${segments.length()}.wav")
    if(active!!.canonicalFile!=destination.canonicalFile)check(active!!.renameTo(destination))
    val end=start+size*1000L/(rate*2)
    segments.put(JSONObject().put("sequence",segments.length()).put("uri",android.net.Uri.fromFile(destination).toString()).put("startMs",start).put("endMs",end))
    journal.put("durationMs",end).remove("activeStartMs");persist();active=null
  }
  @Synchronized fun begin(done:()->Unit){
    if(running)return
    check(journal.optString("status")=="recording")
    running=true
    thread=Thread {
      try {
        val minimum=AudioRecord.getMinBufferSize(rate,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT)
        val audio=AudioRecord(MediaRecorder.AudioSource.MIC,rate,AudioFormat.CHANNEL_IN_MONO,AudioFormat.ENCODING_PCM_16BIT, maxOf(minimum,4096)*2)
        recorder=audio;check(audio.state==AudioRecord.STATE_INITIALIZED)
        audio.startRecording();openSegment();val buffer=ByteArray(4096)
        while(running){
          val count=audio.read(buffer,0,buffer.size);if(!running)break;check(count>0){"Microphone interrupted"}
          synchronized(this){output?.write(buffer,0,count);size+=count;if(size>=rate*2*30){seal();openSegment()}}
        }
      }catch(error:Exception){synchronized(this){journal.put("status","interrupted").put("interrupted",true)}}
      finally {running=false;try{recorder?.stop()}catch(_:Exception){};recorder?.release();recorder=null;synchronized(this){seal();persist()};done()}
    }.apply {start()}
  }
  fun finish(status:String){
    if(!running){if(status=="stopped" && journal.optString("status")=="paused")synchronized(this){journal.put("status","stopped");persist()};return}
    synchronized(this){journal.put("status",status);if(status=="interrupted")journal.put("interrupted",true)}
    running=false;try{recorder?.stop()}catch(_:Exception){};thread?.join(3000)
    check(thread?.isAlive!=true){"Recording is still stopping; retry before upload"}
  }
  @Synchronized fun inspect(directory:File):Map<String,Any?>{
    if(folder==directory && running)return snapshot()
    val saved=JSONObject(File(directory,"capture.json").readText())
    if(saved.optString("status") in listOf("recording","interrupted")){
      check(!running){"Another recording is active"};folder=directory;journal=saved
      val count=journal.getJSONArray("segments").length()
      val files=directory.listFiles()?.filter{it.name.endsWith(".wav") && (it.name.startsWith("active_") || it.name.startsWith("segment_") && it.name.removePrefix("segment_").removeSuffix(".wav").toInt()>=count)}.orEmpty().sortedBy{it.name}
      for(file in files){active=file;output=RandomAccessFile(file,"rw");size=(file.length()-44).toInt().coerceAtLeast(0);start=journal.optLong("activeStartMs",journal.optLong("durationMs"));seal()}
      journal.put("status","interrupted").put("interrupted",true);persist();return snapshot()
    }
    if(!running){folder=directory;journal=saved}
    return jsonMap(saved)
  }
}
