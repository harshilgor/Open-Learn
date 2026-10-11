/** Keep raster attachments portable inside the existing Markdown note format. */
export async function prepareNoteImage(file: File): Promise<string> {
  if (!/^image\/(png|jpeg|webp|gif)$/.test(file.type)) throw new Error('Choose a PNG, JPEG, WebP, or GIF image.');
  if (file.size > 15 * 1024 * 1024) throw new Error('Choose an image smaller than 15 MB.');
  const bitmap = await createImageBitmap(file);
  try {
    const canvas = document.createElement('canvas');
    const scale = Math.min(1, 1400 / Math.max(bitmap.width, bitmap.height));
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext('2d');
    if (!context) throw new Error('This browser could not prepare the image.');
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    for (const quality of [.85, .65, .45, .25]) {
      const data = canvas.toDataURL('image/webp', quality);
      if (data.length <= 75000) return data;
    }
    throw new Error('This image is too detailed. Crop it or choose a smaller image.');
  } finally { bitmap.close(); }
}
