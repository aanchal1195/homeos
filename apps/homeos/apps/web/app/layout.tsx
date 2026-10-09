export const metadata = { title: 'HomeOS JARVIS', description: 'Conversational household operating system' };
export default function RootLayout({ children }:{ children:React.ReactNode }){
  return <html lang="en"><body>{children}</body></html>
}
