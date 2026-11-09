// The Humaital wordmark (docs/assets/humaital-logo.png, 1200 x 198). Always scaled by height so the
// proportions never change; `plate` puts it on a light tile for dark surfaces.
export function BrandLogo({ height = 28, plate = false, className = "" }: { height?: number; plate?: boolean; className?: string }) {
  const img = <img src="/humaital-logo.png" alt="Humaital" style={{ height, width: "auto" }} className={`brand-logo ${className}`} draggable={false} />;
  if (!plate) return img;
  return <span className="brand-plate" style={{ height: height + 14 }}>{img}</span>;
}
