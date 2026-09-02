export type IntrinsicSize = {
  width: number;
  height: number;
};

export function measureIntrinsicSize(): IntrinsicSize {
  const root = document.documentElement;
  const previousRootHeight = root.style.height;
  root.style.height = "max-content";
  const measuredHeight = Math.ceil(root.getBoundingClientRect().height);
  root.style.height = previousRootHeight;

  return {
    width: Math.ceil(document.documentElement.clientWidth),
    height: Math.max(
      measuredHeight,
      Math.ceil(document.body?.scrollHeight || 0),
      1,
    ),
  };
}
