// SPDX-License-Identifier: AGPL-3.0-or-later
// Based on Abyssal Claims — © 2026 Michal Mazurowski — https://something-rare.com

import {
  CONTACT_EMAIL,
  PRIVACY_POLICY,
  SITE_NAME,
  SITE_URL,
  TOOLS_PRIVACY_URL,
  TOOLS_URL,
  type LegalDoc,
} from "./legalContent";

// Translations of PRIVACY_POLICY (the English reference text). Same sections in
// the same order, same `id`s. English is NOT declared binding anywhere in the
// policy, so none of these says so. Terms of Use and About stay English only.
// Polish and German use the formal register, French `vous` (docs/i18n-glossary.md).

export type PolicyLang = "en" | "pl" | "de" | "fr";

const PL: LegalDoc = {
  title: "Polityka prywatności",
  updated: "październik 2026",
  sections: [
    {
      heading: "Kim jesteśmy",
      id: "who-we-are",
      paragraphs: [
        `${SITE_NAME} to dwie usługi prowadzone przez tego samego niezależnego badacza, który jest jedynym administratorem opisanych tu danych: Atlas pod adresem ${SITE_URL}, interaktywna mapa międzynarodowych koncesji na wydobycie z dna głębinowego, wydanych przez Międzynarodowy Organ Dna Morskiego (ISA), oraz Narzędzia ${SITE_NAME} pod adresem ${TOOLS_URL}. W sprawach prywatności dotyczących każdej z tych usług prosimy pisać na adres: ${CONTACT_EMAIL}.`,
      ],
    },
    {
      heading: "Jakie dane zbieramy",
      id: "information-we-collect",
      paragraphs: [
        "Zbieramy niewielką ilość danych, opisaną w kolejnych sekcjach. Nie prowadzimy kont użytkowników ani rejestracji. Nie sprzedajemy danych osobom trzecim.",
      ],
    },
    {
      heading: "Formularz opinii",
      id: "feedback-form",
      paragraphs: [
        "Atlas udostępnia opcjonalny formularz opinii. Jeśli z niego skorzystasz, zbieramy:",
        {
          list: [
            "treść wiadomości i wybraną kategorię (działa dobrze / błąd / sugestia) — wymagane;",
            "adres e-mail — opcjonalnie, tylko jeśli go podasz, abyśmy mogli odpowiedzieć;",
            "jednokierunkowy skrót adresu IP (SHA-256 z solą po stronie serwera, nigdy surowy adres IP) — przechowywany wyłącznie w celu zapobiegania spamowi;",
            "ciąg User-Agent przeglądarki i adres strony w chwili wysłania.",
          ],
        },
        "Zgłoszenia są przechowywane w naszej własnej bazie danych i przekazywane na prywatny kanał Discord prowadzony przez opiekuna serwisu. Adresy e-mail służą wyłącznie do odpowiedzi na wiadomość i nigdy nie są udostępniane. Usunięcia zgłoszenia można zażądać w każdej chwili, pisząc na adres " + CONTACT_EMAIL + ".",
      ],
    },
    {
      heading: `Narzędzia ${SITE_NAME}`,
      id: "abyssal-claims-tools",
      paragraphs: [
        `Narzędzia pod adresem ${TOOLS_URL} odczytują w przeglądarce pliki, które na nie przeciągasz, oraz wklejane linki. Zawartość plików i wklejone linki nigdy nie są wysyłane do nas ani do Google.`,
        `Narzędzia mają własną stronę prywatności, która opisuje tego samego administratora, ten sam kontakt i wspólną zgodę: ${TOOLS_PRIVACY_URL}`,
      ],
    },
    {
      heading: "Twój wybór dotyczący cookies (obie usługi)",
      id: "your-cookie-choice-both-services",
      paragraphs: [
        "Atlas i Narzędzia mają jeden wspólny wybór dotyczący cookies. Jest zapisany w jednym ciasteczku własnym o nazwie ac_consent (wartość granted lub denied) w domenie something-rare.com i obowiązuje 180 dni, dlatego wybór dokonany w jednej usłudze obowiązuje w drugiej i nie jesteś pytany dwa razy.",
        "Link „Ustawienia cookies” w każdej z usług zmienia ten wybór dla obu.",
      ],
    },
    {
      heading: "Google Analytics (GA4)",
      id: "google-analytics-ga4",
      paragraphs: [
        "Używamy Google Analytics 4 (identyfikator pomiaru G-S5HR4WT0ZG), aby zrozumieć, jak odwiedzający korzystają z Atlasu i Narzędzi. Google Analytics ładuje się dopiero po kliknięciu „Akceptuję” w banerze zgody (albo jeśli zgoda została udzielona wcześniej); przed dokonaniem wyboru nic nie jest wysyłane do Google, a po odrzuceniu również nic nie jest wysyłane.",
        "Po udzieleniu zgody GA4 może zbierać typ urządzenia, przeglądarkę, przybliżony region geograficzny, odwiedzane strony i zdarzenia interakcji oraz może zapisywać ciasteczka w domenie something-rare.com. Dane przetwarza Google LLC. Zgodę można wycofać w każdej chwili linkiem „Ustawienia cookies”.",
      ],
    },
    {
      heading: "Licznik odsłon bez cookies",
      id: "cookieless-page-view-counter",
      paragraphs: [
        "Atlas prowadzi licznik odsłon chroniący prywatność, który zapisuje wyłącznie ścieżkę strony i datę — bez cookies, bez adresu IP, bez identyfikatora użytkownika i bez jakichkolwiek danych osobowych. Ten zbiorczy licznik działa niezależnie od Twojego wyboru dotyczącego cookies i jest przechowywany w naszej własnej bazie danych. Służy wyłącznie do ustalenia, które strony są odwiedzane, i jest wyłączony spod wymogu zgody RODO na podstawie przesłanek „ściśle niezbędne” oraz „cele statystyczne bez wpływu na jednostki”.",
      ],
    },
    {
      heading: "Cookies i pamięć lokalna",
      id: "cookies-and-local-storage",
      paragraphs: [
        "Jedyne ciasteczko, które sami zapisujemy, to opisane wyżej ac_consent, które zapamiętuje Twój wybór dotyczący cookies, aby baner nie pojawiał się przy każdej wizycie. Język interfejsu jest zapamiętywany w localStorage przeglądarki. W żadnym z tych miejsc nie przechowuje się danych osobowych. Po udzieleniu zgody cookies może zapisywać Google Analytics.",
        "Wcześniejsze wersje Atlasu przechowywały ten wybór w localStorage; taki wpis jest przenoszony do ciasteczka ac_consent, a następnie usuwany.",
      ],
    },
    {
      heading: "Podkład mapy i dostawcy danych",
      id: "map-imagery-and-data-providers",
      paragraphs: [
        "Mapa przy każdej wizycie pobiera podkład (zdjęcia) z serwerów Esri (server.arcgisonline.com), a mapa w raportach wpływu — z serwerów Carto (basemaps.cartocdn.com). Niektóre warstwy danych, gdy je włączysz, pobierają dane z serwerów swoich dostawców — na przykład storage.googleapis.com dla warstwy wód powierzchniowych JRC. Jak przy każdej osadzonej mapie, te serwery widzą Twój adres IP. Nie zapisujemy przy tym żadnych ciasteczek i nie jest to śledzenie.",
      ],
    },
    {
      heading: "Okres przechowywania danych",
      id: "data-retention",
      paragraphs: [
        "Liczniki odsłon są przechowywane bezterminowo w postaci zbiorczej (bez danych osobowych). Dane Google Analytics są przechowywane przez 14 miesięcy zgodnie z domyślnym ustawieniem GA4. Ciasteczko ac_consent wygasa po 180 dniach i jest zastępowane nowym, gdy użyjesz linku „Ustawienia cookies”; możesz je też usunąć, czyszcząc ciasteczka przeglądarki. Zgłoszenia z formularza opinii są przechowywane do czasu ich ręcznego usunięcia; zawarte w nich adresy e-mail usuwamy na żądanie.",
      ],
    },
    {
      heading: "Podstawa prawna przetwarzania (RODO)",
      id: "legal-basis-for-processing-gdpr",
      paragraphs: [
        "Jeśli przebywasz w EOG lub Wielkiej Brytanii, przetwarzamy dane na podstawie:",
        {
          list: [
            "zgody (art. 6 ust. 1 lit. a RODO) — dla Google Analytics, włączanego dopiero po akceptacji, oraz dla adresu e-mail podanego dobrowolnie w formularzu opinii;",
            "prawnie uzasadnionych interesów (art. 6 ust. 1 lit. f RODO) — dla podstawowego działania serwisu, bezpieczeństwa oraz obsługi zgłoszeń, które nie zawierają adresu e-mail;",
            "celów statystycznych (motyw 162 RODO) — dla zbiorczego licznika odsłon bez cookies.",
          ],
        },
      ],
    },
    {
      heading: "Twoje prawa",
      id: "your-rights",
      paragraphs: [
        "Na mocy RODO i CCPA przysługuje Ci prawo dostępu do danych, ich sprostowania, usunięcia, ograniczenia przetwarzania i przenoszenia, a także prawo sprzeciwu wobec przetwarzania lub rezygnacji ze sprzedaży danych. Aby z nich skorzystać, napisz na adres " + CONTACT_EMAIL + ". W sprawie danych przetwarzanych przez Google zajrzyj na myaccount.google.com.",
      ],
    },
    {
      heading: "Prywatność dzieci",
      id: "children-s-privacy",
      paragraphs: [
        "Nasze usługi nie są skierowane do dzieci poniżej 13. roku życia. Świadomie nie zbieramy danych od dzieci.",
      ],
    },
    {
      heading: "Zmiany tej polityki",
      id: "changes-to-this-policy",
      paragraphs: [
        "Możemy okresowo aktualizować tę politykę. Data na początku strony wskazuje ostatnią zmianę. Dalsze korzystanie z serwisu po zmianach oznacza ich akceptację.",
      ],
    },
    {
      heading: "Kontakt",
      id: "contact",
      paragraphs: [`W sprawach prywatności i żądań dotyczących danych: ${CONTACT_EMAIL}`],
    },
  ],
};

const DE: LegalDoc = {
  title: "Datenschutzerklärung",
  updated: "Oktober 2026",
  sections: [
    {
      heading: "Wer wir sind",
      id: "who-we-are",
      paragraphs: [
        `${SITE_NAME} besteht aus zwei Diensten desselben unabhängigen Forschers, der der alleinige Verantwortliche für die hier beschriebenen Daten ist: dem Atlas unter ${SITE_URL}, einer interaktiven Karte der internationalen Tiefseebergbau-Konzessionen der Internationalen Meeresbodenbehörde (ISA), und den ${SITE_NAME}-Werkzeugen unter ${TOOLS_URL}. Bei Datenschutzfragen zu einem der beiden Dienste wenden Sie sich bitte an: ${CONTACT_EMAIL}.`,
      ],
    },
    {
      heading: "Welche Daten wir erheben",
      id: "information-we-collect",
      paragraphs: [
        "Wir erheben nur wenige Daten, wie in den folgenden Abschnitten beschrieben. Wir betreiben keine Benutzerkonten oder Registrierungssysteme. Wir verkaufen keine Daten an Dritte.",
      ],
    },
    {
      heading: "Feedback-Formular",
      id: "feedback-form",
      paragraphs: [
        "Der Atlas bietet ein optionales Feedback-Formular. Wenn Sie es nutzen, erheben wir:",
        {
          list: [
            "Ihre Nachricht und die gewählte Kategorie (funktioniert gut / Fehler / Vorschlag) — erforderlich;",
            "Ihre E-Mail-Adresse — optional, nur wenn Sie sie angeben, damit wir antworten können;",
            "einen Einweg-Hash Ihrer IP-Adresse (SHA-256 mit serverseitigem Salt, niemals die Roh-IP) — ausschließlich zur Spam-Abwehr gespeichert;",
            "den User-Agent-String Ihres Browsers und die Seiten-URL zum Zeitpunkt des Absendens.",
          ],
        },
        "Einsendungen werden in unserer eigenen Datenbank gespeichert und an einen privaten Discord-Kanal des Betreibers der Website weitergeleitet. E-Mail-Adressen werden nur verwendet, um auf Ihre Nachricht zu antworten, und niemals weitergegeben. Sie können jederzeit die Löschung Ihrer Einsendung verlangen, indem Sie eine E-Mail an " + CONTACT_EMAIL + " senden.",
      ],
    },
    {
      heading: `${SITE_NAME}-Werkzeuge`,
      id: "abyssal-claims-tools",
      paragraphs: [
        `Die Werkzeuge unter ${TOOLS_URL} lesen die Dateien, die Sie darauf ziehen, und die Links, die Sie einfügen, in Ihrem Browser. Der Inhalt Ihrer Dateien und die eingefügten Links werden niemals an uns oder an Google gesendet.`,
        `Die Werkzeuge haben eine eigene Datenschutzseite, die denselben Verantwortlichen, denselben Kontakt und die gemeinsame Einwilligung beschreibt: ${TOOLS_PRIVACY_URL}`,
      ],
    },
    {
      heading: "Ihre Cookie-Entscheidung (beide Dienste)",
      id: "your-cookie-choice-both-services",
      paragraphs: [
        "Atlas und Werkzeuge teilen sich eine Cookie-Entscheidung. Sie wird in einem einzigen Erstanbieter-Cookie namens ac_consent (Wert granted oder denied) auf der Domain something-rare.com gespeichert und gilt 180 Tage. Eine in einem Dienst getroffene Entscheidung gilt daher auch im anderen, und Sie werden nicht zweimal gefragt.",
        "Der Link „Cookie-Einstellungen“ in beiden Diensten ändert die Entscheidung für beide.",
      ],
    },
    {
      heading: "Google Analytics (GA4)",
      id: "google-analytics-ga4",
      paragraphs: [
        "Wir verwenden Google Analytics 4 (Mess-ID G-S5HR4WT0ZG), um zu verstehen, wie Besucher den Atlas und die Werkzeuge nutzen. Google Analytics wird erst geladen, nachdem Sie im Einwilligungsbanner auf „Akzeptieren“ geklickt haben (oder wenn Sie zuvor zugestimmt haben); vor einer Entscheidung wird nichts an Google gesendet, und bei einer Ablehnung wird ebenfalls nichts gesendet.",
        "Nach Ihrer Einwilligung kann GA4 Gerätetyp, Browser, ungefähre geografische Region, besuchte Seiten und Interaktionsereignisse erfassen und Cookies auf something-rare.com setzen. Die Daten werden von Google LLC verarbeitet. Sie können Ihre Einwilligung jederzeit über den Link „Cookie-Einstellungen“ widerrufen.",
      ],
    },
    {
      heading: "Cookie-freier Seitenaufrufzähler",
      id: "cookieless-page-view-counter",
      paragraphs: [
        "Der Atlas betreibt einen datenschutzfreundlichen Seitenaufrufzähler, der nur den Seitenpfad und das Datum speichert — keine Cookies, keine IP-Adresse, keine Nutzerkennung und keinerlei personenbezogene Daten. Dieser aggregierte Zähler läuft unabhängig von Ihrer Cookie-Entscheidung und wird in unserer eigenen Datenbank gespeichert. Er dient ausschließlich dazu, nachzuvollziehen, welche Seiten besucht werden, und ist nach den Grundlagen „unbedingt erforderlich“ und „statistische Zwecke ohne Auswirkung auf Einzelpersonen“ von den Einwilligungsanforderungen der DSGVO ausgenommen.",
      ],
    },
    {
      heading: "Cookies und lokaler Speicher",
      id: "cookies-and-local-storage",
      paragraphs: [
        "Das einzige Cookie, das wir selbst setzen, ist das oben beschriebene ac_consent, das Ihre Cookie-Entscheidung speichert, damit das Banner nicht bei jedem Besuch erscheint. Ihre Oberflächensprache wird im localStorage Ihres Browsers gespeichert. In keinem von beiden werden personenbezogene Daten abgelegt. Nach Ihrer Einwilligung kann Google Analytics Cookies setzen.",
        "Frühere Versionen des Atlas speicherten die Cookie-Entscheidung im localStorage; dieser Eintrag wird in das Cookie ac_consent übernommen und anschließend entfernt.",
      ],
    },
    {
      heading: "Kartenhintergrund und Datenanbieter",
      id: "map-imagery-and-data-providers",
      paragraphs: [
        "Die Karte lädt ihre Hintergrundbilder bei jedem Besuch von Esri (server.arcgisonline.com); die Karte in den Wirkungsberichten nutzt Carto (basemaps.cartocdn.com). Manche Datenebenen laden, sobald Sie sie einschalten, von den Servern ihrer Anbieter — zum Beispiel storage.googleapis.com für die JRC-Oberflächenwasser-Ebene. Wie bei jeder eingebetteten Karte sehen diese Server Ihre IP-Adresse. Wir setzen dafür keine Cookies, und es handelt sich nicht um Tracking.",
      ],
    },
    {
      heading: "Speicherdauer",
      id: "data-retention",
      paragraphs: [
        "Seitenaufrufzahlen werden unbegrenzt in aggregierter Form (ohne personenbezogene Daten) aufbewahrt. Google-Analytics-Daten werden gemäß der Standardeinstellung von GA4 14 Monate gespeichert. Das Cookie ac_consent läuft nach 180 Tagen ab und wird ersetzt, wenn Sie den Link „Cookie-Einstellungen“ verwenden; Sie können es auch löschen, indem Sie die Cookies Ihres Browsers entfernen. Feedback-Einsendungen werden bis zur manuellen Löschung aufbewahrt; darin enthaltene E-Mail-Adressen werden auf Anfrage gelöscht.",
      ],
    },
    {
      heading: "Rechtsgrundlage der Verarbeitung (DSGVO)",
      id: "legal-basis-for-processing-gdpr",
      paragraphs: [
        "Wenn Sie sich im EWR oder im Vereinigten Königreich befinden, verarbeiten wir Daten auf folgender Grundlage:",
        {
          list: [
            "Einwilligung (Art. 6 Abs. 1 lit. a DSGVO) — für Google Analytics, das erst nach Ihrer Zustimmung aktiviert wird, und für eine im Feedback-Formular freiwillig angegebene E-Mail-Adresse;",
            "berechtigte Interessen (Art. 6 Abs. 1 lit. f DSGVO) — für den grundlegenden Betrieb der Website, die Sicherheit und die Bearbeitung von Feedback-Nachrichten ohne E-Mail-Adresse;",
            "statistische Zwecke (Erwägungsgrund 162 DSGVO) — für den cookie-freien aggregierten Seitenaufrufzähler.",
          ],
        },
      ],
    },
    {
      heading: "Ihre Rechte",
      id: "your-rights",
      paragraphs: [
        "Nach DSGVO und CCPA haben Sie das Recht auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung und Übertragbarkeit Ihrer Daten sowie das Recht, der Verarbeitung zu widersprechen oder dem Verkauf von Daten zu widersprechen. Zur Ausübung dieser Rechte schreiben Sie an " + CONTACT_EMAIL + ". Für Daten bei Google besuchen Sie myaccount.google.com.",
      ],
    },
    {
      heading: "Datenschutz für Kinder",
      id: "children-s-privacy",
      paragraphs: [
        "Unsere Dienste richten sich nicht an Kinder unter 13 Jahren. Wir erheben wissentlich keine Daten von Kindern.",
      ],
    },
    {
      heading: "Änderungen dieser Erklärung",
      id: "changes-to-this-policy",
      paragraphs: [
        "Wir können diese Erklärung von Zeit zu Zeit aktualisieren. Das Datum am Anfang zeigt die jüngste Überarbeitung an. Die weitere Nutzung der Website nach Änderungen gilt als Zustimmung.",
      ],
    },
    {
      heading: "Kontakt",
      id: "contact",
      paragraphs: [`Für Datenschutzfragen oder Auskunftsersuchen: ${CONTACT_EMAIL}`],
    },
  ],
};

const FR: LegalDoc = {
  title: "Politique de confidentialité",
  updated: "octobre 2026",
  sections: [
    {
      heading: "Qui sommes-nous",
      id: "who-we-are",
      paragraphs: [
        `${SITE_NAME} se compose de deux services exploités par le même chercheur indépendant, qui est le seul responsable du traitement des données décrites ici : l'Atlas, à l'adresse ${SITE_URL}, une carte interactive des concessions internationales d'exploitation minière des grands fonds délivrées par l'Autorité internationale des fonds marins (AIFM, ISA), et les Outils ${SITE_NAME}, à l'adresse ${TOOLS_URL}. Pour toute question de confidentialité concernant l'un ou l'autre service, écrivez à : ${CONTACT_EMAIL}.`,
      ],
    },
    {
      heading: "Les données que nous collectons",
      id: "information-we-collect",
      paragraphs: [
        "Nous collectons un petit nombre de données, décrites dans les sections suivantes. Nous n'exploitons ni comptes utilisateurs ni système d'inscription. Nous ne vendons pas de données à des tiers.",
      ],
    },
    {
      heading: "Formulaire de commentaires",
      id: "feedback-form",
      paragraphs: [
        "L'Atlas propose un formulaire de commentaires facultatif. Si vous l'utilisez, nous collectons :",
        {
          list: [
            "votre message et la catégorie choisie (fonctionne bien / bogue / suggestion) — obligatoire ;",
            "votre adresse e-mail — facultative, uniquement si vous la fournissez pour que nous puissions répondre ;",
            "une empreinte à sens unique de votre adresse IP (SHA-256 avec un sel côté serveur, jamais l'adresse IP brute) — conservée uniquement pour prévenir le spam ;",
            "la chaîne User-Agent de votre navigateur et l'URL de la page au moment de l'envoi.",
          ],
        },
        "Les envois sont conservés dans notre propre base de données et transmis à un canal Discord privé géré par le responsable du site. Les adresses e-mail servent uniquement à répondre à votre message et ne sont jamais partagées. Vous pouvez demander la suppression de votre envoi à tout moment en écrivant à " + CONTACT_EMAIL + ".",
      ],
    },
    {
      heading: `Outils ${SITE_NAME}`,
      id: "abyssal-claims-tools",
      paragraphs: [
        `Les outils disponibles à l'adresse ${TOOLS_URL} lisent dans votre navigateur les fichiers que vous y déposez et les liens que vous collez. Le contenu de vos fichiers et les liens collés ne sont jamais envoyés ni à nous ni à Google.`,
        `Les Outils ont leur propre page de confidentialité, qui décrit le même responsable du traitement, le même contact et le consentement commun : ${TOOLS_PRIVACY_URL}`,
      ],
    },
    {
      heading: "Votre choix concernant les cookies (les deux services)",
      id: "your-cookie-choice-both-services",
      paragraphs: [
        "L'Atlas et les Outils partagent un seul choix concernant les cookies. Il est enregistré dans un unique cookie propre nommé ac_consent (valeur granted ou denied) sur le domaine something-rare.com, valable 180 jours : un choix fait dans un service s'applique à l'autre et l'on ne vous le demande pas deux fois.",
        "Le lien « Paramètres des cookies » de l'un ou l'autre service modifie ce choix pour les deux.",
      ],
    },
    {
      heading: "Google Analytics (GA4)",
      id: "google-analytics-ga4",
      paragraphs: [
        "Nous utilisons Google Analytics 4 (identifiant de mesure G-S5HR4WT0ZG) pour comprendre comment les visiteurs utilisent l'Atlas et les Outils. Google Analytics n'est chargé qu'après votre clic sur « Accepter » dans la bannière de consentement (ou si vous avez déjà accepté) ; rien n'est envoyé à Google avant que vous ayez fait un choix, et rien n'est envoyé si vous refusez.",
        "Une fois votre accord donné, GA4 peut collecter le type d'appareil, le navigateur, la région géographique approximative, les pages consultées et les événements d'interaction, et peut déposer des cookies sur something-rare.com. Les données sont traitées par Google LLC. Vous pouvez retirer votre consentement à tout moment avec le lien « Paramètres des cookies ».",
      ],
    },
    {
      heading: "Compteur de pages vues sans cookie",
      id: "cookieless-page-view-counter",
      paragraphs: [
        "L'Atlas exploite un compteur de pages vues respectueux de la vie privée, qui n'enregistre que le chemin de la page et la date — aucun cookie, aucune adresse IP, aucun identifiant d'utilisateur et aucune donnée personnelle d'aucune sorte. Ce compteur agrégé fonctionne quel que soit votre choix concernant les cookies et est conservé dans notre propre base de données. Il sert uniquement à savoir quelles pages sont consultées et est exempté des exigences de consentement du RGPD au titre des bases « strictement nécessaire » et « finalités statistiques sans incidence sur les personnes ».",
      ],
    },
    {
      heading: "Cookies et stockage local",
      id: "cookies-and-local-storage",
      paragraphs: [
        "Le seul cookie que nous déposons nous-mêmes est ac_consent, décrit plus haut, qui mémorise votre choix concernant les cookies afin que la bannière n'apparaisse pas à chaque visite. Votre langue d'interface est mémorisée dans le localStorage de votre navigateur. Aucune donnée personnelle n'est stockée dans l'un ou l'autre. Des cookies peuvent être déposés par Google Analytics après votre consentement.",
        "Les versions antérieures de l'Atlas conservaient ce choix dans le localStorage ; cette entrée est reprise dans le cookie ac_consent, puis supprimée.",
      ],
    },
    {
      heading: "Fond de carte et fournisseurs de données",
      id: "map-imagery-and-data-providers",
      paragraphs: [
        "La carte charge son fond d'imagerie depuis Esri (server.arcgisonline.com) à chaque visite ; la carte des rapports d'impact utilise Carto (basemaps.cartocdn.com). Certaines couches de données, une fois activées, se chargent depuis les serveurs de leurs fournisseurs — par exemple storage.googleapis.com pour la couche des eaux de surface du JRC. Comme pour toute carte intégrée, ces serveurs voient votre adresse IP. Nous ne déposons aucun cookie pour cela, et il ne s'agit pas de suivi.",
      ],
    },
    {
      heading: "Durée de conservation",
      id: "data-retention",
      paragraphs: [
        "Les compteurs de pages vues sont conservés indéfiniment sous forme agrégée (sans donnée personnelle). Les données de Google Analytics sont conservées 14 mois, selon le réglage par défaut de GA4. Le cookie ac_consent expire au bout de 180 jours et est remplacé lorsque vous utilisez le lien « Paramètres des cookies » ; vous pouvez aussi le supprimer en effaçant les cookies de votre navigateur. Les commentaires envoyés sont conservés jusqu'à leur suppression manuelle ; les adresses e-mail qu'ils contiennent sont supprimées sur demande.",
      ],
    },
    {
      heading: "Base juridique du traitement (RGPD)",
      id: "legal-basis-for-processing-gdpr",
      paragraphs: [
        "Si vous vous trouvez dans l'EEE ou au Royaume-Uni, nous traitons les données sur les bases suivantes :",
        {
          list: [
            "le consentement (article 6, paragraphe 1, point a du RGPD) — pour Google Analytics, activé uniquement après votre acceptation, et pour toute adresse e-mail fournie volontairement dans le formulaire de commentaires ;",
            "les intérêts légitimes (article 6, paragraphe 1, point f du RGPD) — pour le fonctionnement de base du site, la sécurité et le traitement des commentaires qui ne contiennent pas d'adresse e-mail ;",
            "les finalités statistiques (considérant 162 du RGPD) — pour le compteur de pages vues agrégé et sans cookie.",
          ],
        },
      ],
    },
    {
      heading: "Vos droits",
      id: "your-rights",
      paragraphs: [
        "En vertu du RGPD et du CCPA, vous avez le droit d'accéder à vos données, de les rectifier, de les effacer, d'en limiter le traitement ou de les porter, ainsi que de vous opposer au traitement ou de refuser la vente de données. Pour exercer ces droits, écrivez à " + CONTACT_EMAIL + ". Pour les données détenues par Google, consultez myaccount.google.com.",
      ],
    },
    {
      heading: "Protection des enfants",
      id: "children-s-privacy",
      paragraphs: [
        "Nos services ne s'adressent pas aux enfants de moins de 13 ans. Nous ne collectons pas sciemment de données concernant des enfants.",
      ],
    },
    {
      heading: "Modifications de cette politique",
      id: "changes-to-this-policy",
      paragraphs: [
        "Nous pouvons mettre à jour cette politique de temps à autre. La date indiquée en haut correspond à la dernière révision. La poursuite de l'utilisation du site après des modifications vaut acceptation.",
      ],
    },
    {
      heading: "Contact",
      id: "contact",
      paragraphs: [`Pour toute question de confidentialité ou demande relative aux données : ${CONTACT_EMAIL}`],
    },
  ],
};

export const PRIVACY_BY_LANG: Record<PolicyLang, LegalDoc> = {
  en: PRIVACY_POLICY,
  pl: PL,
  de: DE,
  fr: FR,
};
