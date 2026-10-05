package openlearn.capture

import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import android.content.Intent
import android.os.Build
import java.io.File
import java.net.URI

class LectureCaptureModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("LectureCapture")
    AsyncFunction("start") { directory: String, id: String ->
      val context = appContext.reactContext ?: error("Application unavailable")
      val folder = File(URI(directory)).canonicalFile
      require(folder.toPath().startsWith(context.filesDir.canonicalFile.toPath())) { "Private documents directory required" }
      Capture.prepare(folder,id)
      val intent=Intent(context,CaptureService::class.java)
      if(Build.VERSION.SDK_INT>=26) context.startForegroundService(intent) else context.startService(intent)
      Capture.snapshot()
    }
    AsyncFunction("stop") { Capture.finish("stopped");Capture.snapshot() }
    AsyncFunction("pause") { Capture.finish("paused");Capture.snapshot() }
    AsyncFunction("resume") {
      val context=appContext.reactContext ?: error("Application unavailable")
      Capture.resume()
      val intent=Intent(context,CaptureService::class.java)
      if(Build.VERSION.SDK_INT>=26) context.startForegroundService(intent) else context.startService(intent)
      Capture.snapshot()
    }
    AsyncFunction("inspect") { directory: String ->
      val context=appContext.reactContext ?: error("Application unavailable")
      val folder=File(URI(directory)).canonicalFile
      require(folder.toPath().startsWith(context.filesDir.canonicalFile.toPath()))
      Capture.inspect(folder)
    }
  }
}
