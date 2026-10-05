Pod::Spec.new do |s|
  s.name = 'LectureCapture'
  s.version = '0.1.0'
  s.summary = 'Durable private lecture segments'
  s.description = s.summary
  s.author = 'Open Learn'
  s.homepage = 'https://example.invalid/openlearn'
  s.license = 'MIT'
  s.platform = :ios, '16.0'
  s.source = { git: '' }
  s.static_framework = true
  s.dependency 'ExpoModulesCore'
  s.source_files = '**/*.{h,m,mm,swift}'
end
