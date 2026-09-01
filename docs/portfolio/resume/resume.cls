\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{resume}[2026/08/18 Self-contained public resume class]

\LoadClass[UTF8,11pt,a4paper,fontset=fandol]{ctexart}

\RequirePackage{fontspec}
\setmainfont{TeX Gyre Termes}
\setsansfont{TeX Gyre Heros}

\RequirePackage[
  a4paper,
  left=0.25in,
  right=0.25in,
  top=0.12in,
  bottom=0.15in,
  nohead,
  nofoot
]{geometry}
\RequirePackage{xifthen}
\RequirePackage{titlesec}
\RequirePackage{enumitem}

\setlength{\parindent}{0pt}
\linespread{0.93}
\AtBeginDocument{\pagestyle{empty}}
\setlist{noitemsep}
\setlist[itemize]{topsep=0.18em, leftmargin=1.35pc}
\setlist[enumerate]{topsep=0.18em, leftmargin=1.35pc}

\titleformat{\section}
  {\large\bfseries\raggedright}
  {}{0em}{}
  [\titlerule]
\titlespacing*{\section}{0cm}{*0.25}{*0.15}

\titleformat{\subsection}
  {\normalsize\raggedright}
  {}{0em}{}
\titlespacing*{\subsection}{0cm}{*0.2}{*0.05}

\newcommand{\datedsection}[2]{%
  \section[#1]{#1 \hfill #2}%
}

\newcommand{\datedsubsection}[2]{%
  \subsection[#1]{#1 \hfill #2}%
}

\newcommand{\datedline}[2]{%
  {\par #1 \hfill #2 \par}%
}

\newcommand{\name}[1]{%
  \centerline{\LARGE\bfseries{#1}}%
  \vspace{0.15ex}%
}

\newcommand{\contactInfo}[2]{%
  \centerline{\sffamily\normalsize{手机：#1 \textperiodcentered\ 邮箱：#2}}%
  \vspace{0.2ex}%
}

\newcommand{\otherInfo}[4]{%
  \centerline{\sffamily\normalsize{#1}%
    \ifthenelse{\isempty{#2}}{}{\textperiodcentered\ #2}%
    \ifthenelse{\isempty{#3}}{}{\textperiodcentered\ #3}%
    \ifthenelse{\isempty{#4}}{}{\textperiodcentered\ #4}%
  }%
}

\newcommand{\role}[2]{%
  {\par \textit{#1}~#2 \par}%
  \vspace{0.2ex}%
}
