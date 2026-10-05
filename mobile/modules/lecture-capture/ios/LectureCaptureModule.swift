import ExpoModulesCore
import AVFoundation

public class LectureCaptureModule: Module {
  private let capture = SegmentedCapture()
  public func definition() -> ModuleDefinition {
    Name("LectureCapture")
    AsyncFunction("start") { (directory:String,id:String) in try self.capture.start(directory,id) }
    AsyncFunction("stop") { try self.capture.stop("stopped") }
    AsyncFunction("pause") { try self.capture.stop("paused") }
    AsyncFunction("resume") { try self.capture.resume() }
    AsyncFunction("inspect") { (directory:String) in try self.capture.inspect(directory) }
  }
}

private final class SegmentedCapture {
  private let queue = DispatchQueue(label:"openlearn.capture")
  private var engine:AVAudioEngine?
  private var folder:URL?
  private var journal:[String:Any]=[:]
  private var file:FileHandle?
  private var active:URL?
  private var size=0
  private var rate=48000
  private var segmentStart=0
  private var observer:NSObjectProtocol?
  private func directory(_ value:String) throws -> URL {
    guard let url=URL(string:value),url.isFileURL else {throw NSError(domain:"capture",code:1)}
    let path=url.standardizedFileURL.resolvingSymlinksInPath()
    let root=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0].standardizedFileURL.path+"/"
    guard path.path.hasPrefix(root) else {throw NSError(domain:"capture",code:2)}
    return path
  }
  private func now()->Int {Int(Date().timeIntervalSince1970*1000)}
  private func persist() throws {
    guard let folder=folder else{return}
    let data=try JSONSerialization.data(withJSONObject:journal)
    try data.write(to:folder.appendingPathComponent("capture.json"),options:.atomic)
    let handle=try FileHandle(forWritingTo:folder.appendingPathComponent("capture.json"));try handle.synchronize();try handle.close()
  }
  func start(_ value:String,_ id:String)throws->[String:Any] {
    try queue.sync {
      guard engine==nil,journal["status"] as? String != "paused",id.range(of:"^rec_[a-f0-9]{32}$",options:.regularExpression) != nil else{throw NSError(domain:"capture",code:3)}
      folder=try directory(value);try FileManager.default.createDirectory(at:folder!,withIntermediateDirectories:true)
      guard !FileManager.default.fileExists(atPath:folder!.appendingPathComponent("capture.json").path) else{throw NSError(domain:"capture",code:4)}
      journal=["recordingId":id,"directory":folder!.absoluteString,"status":"recording","startedAtMs":now(),"durationMs":0,"interrupted":false,"segments":[[String:Any]]()]
      try persist();try begin();return journal
    }
  }
  private func begin()throws {
    let session=AVAudioSession.sharedInstance()
    try session.setCategory(.playAndRecord,mode:.default,options:[.defaultToSpeaker,.allowBluetoothHFP]);try session.setActive(true)
    let audio=AVAudioEngine();let format=audio.inputNode.outputFormat(forBus:0)
    guard format.sampleRate>0,format.sampleRate<=48000 else{throw NSError(domain:"capture",code:5)}
    rate=Int(format.sampleRate);try open()
    audio.inputNode.installTap(onBus:0,bufferSize:2048,format:format) { [weak self] buffer,_ in
      guard let self=self,let samples=buffer.floatChannelData?[0] else{return}
      var bytes=Data(capacity:Int(buffer.frameLength)*2)
      for i in 0..<Int(buffer.frameLength){var sample=Int16(max(-1,min(1,samples[i]))*32767).littleEndian;withUnsafeBytes(of:&sample){bytes.append(contentsOf:$0)}}
      self.queue.async {
        guard self.engine != nil else{return}
        do {try self.file?.write(contentsOf:bytes);self.size+=bytes.count;if self.size>=self.rate*2*30 {try self.seal();try self.open()}}
        catch {try? self.finish("interrupted")}
      }
    }
    engine=audio
    observer=NotificationCenter.default.addObserver(forName:AVAudioSession.interruptionNotification,object:session,queue:nil) { [weak self] _ in self?.queue.async {try? self?.finish("interrupted")} }
    audio.prepare();try audio.start()
  }
  private func open()throws {
    let segments=journal["segments"] as? [[String:Any]] ?? []
    active=folder!.appendingPathComponent("active_\(segments.count).wav")
    FileManager.default.createFile(atPath:active!.path,contents:Data(count:44))
    file=try FileHandle(forWritingTo:active!);try file!.seekToEnd();size=0
    segmentStart=now()-(journal["startedAtMs"] as! Int)
    journal["activeStartMs"]=segmentStart;journal["sampleRate"]=rate;try persist()
  }
  private func header(_ length:Int)->Data {
    var data=Data("RIFF".utf8)
    func n<T:FixedWidthInteger>(_ value:T){var v=value.littleEndian;withUnsafeBytes(of:&v){data.append(contentsOf:$0)}}
    n(UInt32(length+36));data.append(Data("WAVEfmt ".utf8));n(UInt32(16));n(UInt16(1));n(UInt16(1));n(UInt32(rate));n(UInt32(rate*2));n(UInt16(2));n(UInt16(16));data.append(Data("data".utf8));n(UInt32(length));return data
  }
  private func seal()throws {
    guard let file=file,let active=active else{return}
    try file.seek(toOffset:0);try file.write(contentsOf:header(size));try file.synchronize();try file.close();self.file=nil
    if size==0{try FileManager.default.removeItem(at:active);return}
    var segments=journal["segments"] as? [[String:Any]] ?? []
    let destination=folder!.appendingPathComponent("segment_\(segments.count).wav")
    if active != destination {try FileManager.default.moveItem(at:active,to:destination)}
    let end=segmentStart+size*1000/(rate*2)
    segments.append(["sequence":segments.count,"uri":destination.absoluteString,"startMs":segmentStart,"endMs":end]);journal["segments"]=segments;journal["durationMs"]=end;journal.removeValue(forKey:"activeStartMs");try persist();self.active=nil
  }
  private func finish(_ status:String)throws {
    if let audio=engine {audio.stop();audio.inputNode.removeTap(onBus:0);engine=nil}
    if let observer=observer{NotificationCenter.default.removeObserver(observer);self.observer=nil}
    journal["status"]=status;if status=="interrupted"{journal["interrupted"]=true}
    try seal();try persist();try? AVAudioSession.sharedInstance().setActive(false,options:.notifyOthersOnDeactivation)
  }
  func stop(_ status:String)throws->[String:Any] {try queue.sync {try finish(status);return journal}}
  func resume()throws->[String:Any] {try queue.sync {guard journal["status"] as? String == "paused" else{throw NSError(domain:"capture",code:6)};journal["status"]="recording";journal["interrupted"]=true;try persist();try begin();return journal}}
  func inspect(_ value:String)throws->[String:Any] {
    try queue.sync {
      let directory=try self.directory(value)
      if engine != nil,folder==directory{var current=journal;if file != nil{current["durationMs"]=segmentStart+size*1000/(rate*2)};return current}
      var saved=try JSONSerialization.jsonObject(with:Data(contentsOf:directory.appendingPathComponent("capture.json"))) as! [String:Any]
      if ["recording","interrupted"].contains(saved["status"] as? String ?? "") {
        guard engine==nil else{throw NSError(domain:"capture",code:7)}
        folder=directory;journal=saved;rate=saved["sampleRate"] as? Int ?? 48000
        let count=(saved["segments"] as? [[String:Any]] ?? []).count
        for url in try FileManager.default.contentsOfDirectory(at:directory,includingPropertiesForKeys:nil).filter({$0.pathExtension=="wav" && ($0.lastPathComponent.hasPrefix("active_") || $0.lastPathComponent.hasPrefix("segment_") && (Int($0.deletingPathExtension().lastPathComponent.replacingOccurrences(of:"segment_",with:"")) ?? -1)>=count)}).sorted(by:{$0.lastPathComponent<$1.lastPathComponent}) {
          active=url;file=try FileHandle(forUpdating:url);size=max(0,Int(try file!.seekToEnd())-44);segmentStart=saved["activeStartMs"] as? Int ?? 0;try seal()
        }
        journal["status"]="interrupted";journal["interrupted"]=true;try persist();saved=journal
      }
      if engine==nil {folder=directory;journal=saved}
      return saved
    }
  }
}
