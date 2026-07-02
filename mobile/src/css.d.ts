// Allow importing CSS / CSS-module files (used by template web components).
declare module '*.css';
declare module '*.module.css' {
  const classes: { [key: string]: string };
  export default classes;
}
