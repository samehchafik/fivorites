// Le fichier de localisation : tous les textes de l'interface, les quatre
// langues côte à côte.
//
// Côte à côte, et pas un fichier par langue : une clé traduite dans trois
// langues sur quatre se voit en relecture de diff, alors qu'elle se perd
// entre quatre fichiers. Le type le garantit d'ailleurs — `Phrase` exige les
// quatre, un oubli casse le build plutôt que la page.
//
// Ce qui N'EST PAS ici : les données. Un titre d'œuvre, un genre TMDB, un nom
// de plateforme viennent de l'index dans la langue demandée (voir
// `fiv_webapp.recherche`) — les traduire ici reviendrait à inventer un
// catalogue. Les rôles, eux, arrivent du serveur en CODES (`realisation`,
// `interpretation`…) justement pour être traduits ici.

import { LANGUE_DEFAUT, LANGUE_LOCALES, LANGUE_SENS, type Langue } from './langues'

/** Une phrase dans les quatre langues. Aucune n'est optionnelle. */
type Phrase = Record<Langue, string>

/** Les valeurs interpolées dans une phrase : `{nombre}`, `{titre}`… */
type Valeurs = Record<string, string | number>

export const TEXTES = {
  // --- La coque du site : en-tête, pied, voile d'avant-première ----------
  'nav.series': { fr: 'Séries', en: 'Series', es: 'Series', ar: 'مسلسلات' },
  'nav.films': { fr: 'Films', en: 'Movies', es: 'Películas', ar: 'أفلام' },
  'nav.livres': { fr: 'Livres', en: 'Books', es: 'Libros', ar: 'كتب' },
  'nav.accueil': { fr: 'Accueil', en: 'Home', es: 'Inicio', ar: 'الرئيسية' },
  'nav.langues': { fr: 'Langue', en: 'Language', es: 'Idioma', ar: 'اللغة' },
  'nav.aria': { fr: 'Navigation principale', en: 'Main navigation', es: 'Navegación principal', ar: 'التنقل الرئيسي' },
  'pied.baseline': {
    fr: 'FIVO — vos cinq meilleures œuvres, vos prochaines passions.',
    en: 'FIVO — your five favourites, your next passions.',
    es: 'FIVO — tus cinco obras favoritas, tus próximas pasiones.',
    ar: 'FIVO — أعمالك الخمسة المفضّلة، وشغفك القادم.',
  },
  'pied.aria': { fr: 'Pied de page', en: 'Footer', es: 'Pie de página', ar: 'تذييل الصفحة' },
  'cta.suggestions': {
    fr: 'Obtenez des suggestions personnalisées !',
    en: 'Get suggestions made for you!',
    es: '¡Obtén sugerencias personalizadas!',
    ar: 'احصل على اقتراحات مخصّصة لك!',
  },
  'voile.titre': {
    fr: 'Bienvenue en avant-première !',
    en: 'Welcome to the preview!',
    es: '¡Bienvenido a la avanzada!',
    ar: 'مرحبًا بك في العرض المسبق!',
  },
  'voile.texte': {
    fr: "Le site est encore en construction : le catalogue se remplit, le moteur apprend. Ce que vous voyez peut bouger d'un jour à l'autre — mais tout ce qui est là marche pour de vrai.",
    en: 'The site is still being built: the catalogue is filling up, the engine is learning. What you see may change from one day to the next — but everything here really works.',
    es: 'El sitio todavía está en construcción: el catálogo se va llenando, el motor aprende. Lo que ves puede cambiar de un día para otro, pero todo lo que está aquí funciona de verdad.',
    ar: 'الموقع لا يزال قيد الإنشاء: الفهرس يتوسّع، والمحرّك يتعلّم. ما ترى قد يتغيّر من يوم إلى آخر — لكن كل ما هو موجود هنا يعمل فعلًا.',
  },
  'voile.ok': { fr: 'OK, montre-moi !', en: 'OK, show me!', es: '¡OK, muéstrame!', ar: 'حسنًا، أرِني!' },

  // --- L'îlot : univers, bandeau, onglets --------------------------------
  'univers.aria': { fr: 'Choisir un univers', en: 'Choose a universe', es: 'Elegir un universo', ar: 'اختر عالمًا' },
  'type.series': { fr: 'Série', en: 'Series', es: 'Serie', ar: 'مسلسل' },
  'type.films': { fr: 'Film', en: 'Movie', es: 'Película', ar: 'فيلم' },
  'type.livres': { fr: 'Livre', en: 'Book', es: 'Libro', ar: 'كتاب' },
  'bandeau.series': {
    fr: 'Fivo va trouver des séries pour vous !',
    en: 'Fivo will find series for you!',
    es: '¡Fivo va a encontrar series para ti!',
    ar: 'سيجد لك فيفو مسلسلات!',
  },
  'bandeau.films': {
    fr: 'Fivo va trouver des films pour vous !',
    en: 'Fivo will find movies for you!',
    es: '¡Fivo va a encontrar películas para ti!',
    ar: 'سيجد لك فيفو أفلامًا!',
  },
  'bandeau.livres': {
    fr: 'Fivo va trouver des livres pour vous !',
    en: 'Fivo will find books for you!',
    es: '¡Fivo va a encontrar libros para ti!',
    ar: 'سيجد لك فيفو كتبًا!',
  },
  'bandeau.phrase': {
    fr: "Fivo, notre moteur d'inspiration culturelle, apprend de chaque geste : cherchez, classez — et regardez vos suggestions se préciser.",
    en: 'Fivo, our culture engine, learns from every move: search, sort — and watch your suggestions sharpen.',
    es: 'Fivo, nuestro motor de inspiración cultural, aprende de cada gesto: busca, clasifica — y verás cómo tus sugerencias se afinan.',
    ar: 'فيفو، محرّك الإلهام الثقافي، يتعلّم من كل حركة: ابحث، صنّف — وشاهد اقتراحاتك تصبح أدقّ.',
  },
  'langue.legende': {
    fr: 'Langue du site et de la recherche',
    en: 'Site and search language',
    es: 'Idioma del sitio y de la búsqueda',
    ar: 'لغة الموقع والبحث',
  },
  'onglet.aria': {
    fr: 'Recherche, suggestions ou ma liste',
    en: 'Search, suggestions or my list',
    es: 'Búsqueda, sugerencias o mi lista',
    ar: 'البحث أو الاقتراحات أو قائمتي',
  },
  'onglet.recherche': { fr: 'Recherche', en: 'Search', es: 'Buscar', ar: 'البحث' },
  'onglet.suggestions': { fr: 'Mes suggestions', en: 'My suggestions', es: 'Mis sugerencias', ar: 'اقتراحاتي' },
  'onglet.liste': { fr: 'Ma liste', en: 'My list', es: 'Mi lista', ar: 'قائمتي' },

  // --- Recherche ---------------------------------------------------------
  // Court exprès : sur un téléphone, un placeholder de dix mots se coupe au
  // milieu (« un auteu ») et n'apprend plus rien. Les exemples vivent dans
  // `recherche.repos`, juste dessous, où ils tiennent.
  'recherche.placeholder': {
    fr: 'Un titre, un genre, un acteur…',
    en: 'A title, a genre, an actor…',
    es: 'Un título, un género, un actor…',
    ar: 'عنوان، تصنيف، ممثّل…',
  },
  'recherche.aria': { fr: 'Rechercher une œuvre', en: 'Search for a work', es: 'Buscar una obra', ar: 'ابحث عن عمل' },
  'recherche.repos': {
    fr: "Cherchez les œuvres qui vous ont marqué, puis classez-les : c'est comme ça que FIVO apprend vos goûts. Un titre (« Dune »), un genre (« policier »), un nom (« Spielberg ») — tout marche.",
    en: 'Search for the works that stayed with you, then sort them: that is how FIVO learns your taste. A title (“Dune”), a genre (“crime”), a name (“Spielberg”) — all of it works.',
    es: 'Busca las obras que te marcaron y clasifícalas: así es como FIVO aprende tus gustos. Un título («Dune»), un género («policíaco»), un nombre («Spielberg»): todo vale.',
    ar: 'ابحث عن الأعمال التي أثّرت فيك ثم صنّفها: بهذه الطريقة يتعلّم فيفو ذوقك. عنوان («ديون») أو تصنيف («جريمة») أو اسم («سبيلبرغ») — كلها تعمل.',
  },
  'recherche.erreur': {
    fr: 'La recherche ne répond pas — réessayez dans un instant.',
    en: 'Search is not responding — try again in a moment.',
    es: 'La búsqueda no responde: inténtalo de nuevo en un momento.',
    ar: 'البحث لا يستجيب — أعد المحاولة بعد لحظات.',
  },
  'recherche.vide': {
    fr: 'Rien trouvé pour « {texte} ». Essayez autrement ?',
    en: 'Nothing found for “{texte}”. Try something else?',
    es: 'No se encontró nada para «{texte}». ¿Probamos de otra forma?',
    ar: 'لا نتائج لـ «{texte}». جرّب صيغة أخرى؟',
  },
  'recherche.vide_filtres': {
    fr: 'Rien trouvé pour « {texte} » avec ces filtres. Essayez autrement ?',
    en: 'Nothing found for “{texte}” with these filters. Try something else?',
    es: 'No se encontró nada para «{texte}» con estos filtros. ¿Probamos de otra forma?',
    ar: 'لا نتائج لـ «{texte}» بهذه المرشّحات. جرّب صيغة أخرى؟',
  },
  'recherche.compte': { fr: '{montres} sur {total}', en: '{montres} of {total}', es: '{montres} de {total}', ar: '{montres} من {total}' },
  'recherche.compte_approche': {
    fr: '{montres} sur plus de {total}',
    en: '{montres} of more than {total}',
    es: '{montres} de más de {total}',
    ar: '{montres} من أكثر من {total}',
  },
  'recherche.charger': { fr: 'Charger plus', en: 'Load more', es: 'Cargar más', ar: 'تحميل المزيد' },
  'commun.chargement': { fr: 'Chargement…', en: 'Loading…', es: 'Cargando…', ar: 'جارٍ التحميل…' },
  'commun.fermer': { fr: 'Fermer', en: 'Close', es: 'Cerrar', ar: 'إغلاق' },

  // --- Filtres -----------------------------------------------------------
  'filtres.filtrer_par': { fr: 'Filtrer par {dimension}', en: 'Filter by {dimension}', es: 'Filtrar por {dimension}', ar: 'تصفية حسب {dimension}' },
  'filtres.effacer': { fr: 'tout effacer', en: 'clear all', es: 'borrar todo', ar: 'محو الكل' },
  'filtres.oeuvre_une': { fr: '{nombre} œuvre', en: '{nombre} work', es: '{nombre} obra', ar: 'عمل واحد' },
  'filtres.oeuvres': { fr: '{nombre} œuvres', en: '{nombre} works', es: '{nombre} obras', ar: '{nombre} عمل' },
  'filtres.genres': { fr: 'Genres', en: 'Genres', es: 'Géneros', ar: 'التصنيفات' },
  'filtres.plateformes': { fr: 'Plateformes', en: 'Platforms', es: 'Plataformas', ar: 'المنصّات' },

  // --- Les trois gestes --------------------------------------------------
  'geste.aime_pas': { fr: "J'aime pas", en: 'Not for me', es: 'No me gusta', ar: 'لا يعجبني' },
  'geste.aime': { fr: "J'ai vu & aimé", en: 'Seen & loved', es: 'Visto y me gustó', ar: 'شاهدته وأحببته' },
  'geste.a_voir': { fr: 'Je veux voir !', en: 'Want to see!', es: '¡Quiero verlo!', ar: 'أريد مشاهدته!' },
  'geste.groupe': { fr: 'Classer cette œuvre', en: 'Sort this work', es: 'Clasificar esta obra', ar: 'صنّف هذا العمل' },
  'geste.inclassable': {
    fr: 'Œuvre pas encore classable',
    en: 'This work cannot be sorted yet',
    es: 'Esta obra aún no se puede clasificar',
    ar: 'لا يمكن تصنيف هذا العمل بعد',
  },

  // --- Carte -------------------------------------------------------------
  'carte.voir_fiche': { fr: 'Voir la fiche de {titre}', en: 'Open the page for {titre}', es: 'Ver la ficha de {titre}', ar: 'عرض صفحة {titre}' },
  'carte.sans_titre': { fr: 'Sans titre', en: 'Untitled', es: 'Sin título', ar: 'بلا عنوان' },
  'carte.cette_oeuvre': { fr: 'cette œuvre', en: 'this work', es: 'esta obra', ar: 'هذا العمل' },
  'carte.annee_inconnue': { fr: 'année inconnue', en: 'year unknown', es: 'año desconocido', ar: 'سنة غير معروفة' },
  'carte.note': {
    fr: 'Note des votants : {note} sur 10',
    en: 'Voter score: {note} out of 10',
    es: 'Nota de los votantes: {note} sobre 10',
    ar: 'تقييم المصوّتين: {note} من 10',
  },

  // --- Suggestions : présentation ---------------------------------------
  'vue.groupe': { fr: 'Présentation des suggestions', en: 'Suggestion layout', es: 'Presentación de las sugerencias', ar: 'طريقة عرض الاقتراحات' },
  'vue.pile': { fr: 'Pile', en: 'Stack', es: 'Pila', ar: 'بطاقات' },
  'vue.liste': { fr: 'Liste', en: 'List', es: 'Lista', ar: 'قائمة' },
  'vue.pile_titre': {
    fr: "Une œuvre à la fois, à jeter d'un geste",
    en: 'One work at a time, flicked away',
    es: 'Una obra a la vez, para descartar con un gesto',
    ar: 'عمل واحد في كل مرة، تُبعده بحركة',
  },
  'vue.liste_titre': {
    fr: 'Toutes les propositions, à comparer',
    en: 'Every suggestion, side by side',
    es: 'Todas las propuestas, para comparar',
    ar: 'كل الاقتراحات، للمقارنة',
  },
  'pile.passer': { fr: 'Passer', en: 'Skip', es: 'Pasar', ar: 'تخطّي' },
  'pile.vide': {
    fr: "Plus de carte pour l'instant — revenez après avoir classé quelques œuvres.",
    en: 'No more cards for now — come back once you have sorted a few works.',
    es: 'No hay más cartas por ahora: vuelve cuando hayas clasificado algunas obras.',
    ar: 'لا مزيد من البطاقات الآن — عد بعد تصنيف بعض الأعمال.',
  },
  'pile.aria': {
    fr: '{titre} — flèches pour classer, entrée pour la fiche',
    en: '{titre} — arrow keys to sort, Enter for the full page',
    es: '{titre} — flechas para clasificar, Enter para la ficha',
    ar: '{titre} — الأسهم للتصنيف، Enter لعرض الصفحة',
  },
  'pile.voir_fiche': { fr: 'Voir la fiche', en: 'Open the full page', es: 'Ver la ficha', ar: 'عرض الصفحة' },

  // --- Suggestions : messages et raisons --------------------------------
  'suggestions.erreur': {
    fr: 'Les suggestions ne répondent pas — réessayez dans un instant.',
    en: 'Suggestions are not responding — try again in a moment.',
    es: 'Las sugerencias no responden: inténtalo de nuevo en un momento.',
    ar: 'الاقتراحات لا تستجيب — أعد المحاولة بعد لحظات.',
  },
  'suggestions.commencez': {
    fr: "Commencez par l'onglet Recherche : classez quelques œuvres que vous avez vues et aimées — c'est la graine de vos suggestions.",
    en: 'Start with the Search tab: sort a few works you have seen and loved — that is the seed of your suggestions.',
    es: 'Empieza por la pestaña Buscar: clasifica algunas obras que hayas visto y te hayan gustado; son la semilla de tus sugerencias.',
    ar: 'ابدأ من تبويب البحث: صنّف بعض الأعمال التي شاهدتها وأحببتها — فهي بذرة اقتراحاتك.',
  },
  'suggestions.aucun_resultat': {
    fr: "Rien à proposer dans cet univers pour l'instant — vos coups de cœur y sont d'un autre univers, ou leur fiche n'est pas encore indexée. Classez une œuvre d'ici, et la liste se remplit.",
    en: 'Nothing to suggest in this universe yet — your favourites belong to another one, or their pages are not indexed yet. Sort a work from here and the list fills up.',
    es: 'Nada que proponer en este universo por ahora: tus favoritos son de otro universo, o sus fichas aún no están indexadas. Clasifica una obra de aquí y la lista se llenará.',
    ar: 'لا شيء لاقتراحه في هذا العالم بعد — مفضّلاتك من عالم آخر، أو صفحاتها غير مفهرسة بعد. صنّف عملًا من هنا وستمتلئ القائمة.',
  },
  'raison.corrobore_un': {
    fr: "Proche de vos coups de cœur ET dans le top d'un membre qui partage vos goûts",
    en: 'Close to your favourites AND in the top five of a member who shares your taste',
    es: 'Cercana a tus favoritos Y en el top de un miembro con tus gustos',
    ar: 'قريب من مفضّلاتك وفي قائمة عضو يشاركك الذوق',
  },
  'raison.corrobore': {
    fr: 'Proche de vos coups de cœur ET dans le top de {nombre} membres qui partagent vos goûts',
    en: 'Close to your favourites AND in the top five of {nombre} members who share your taste',
    es: 'Cercana a tus favoritos Y en el top de {nombre} miembros con tus gustos',
    ar: 'قريب من مفضّلاتك وفي قوائم {nombre} أعضاء يشاركونك الذوق',
  },
  'raison.voisins_un': {
    fr: "Dans le top d'un membre qui partage vos goûts",
    en: 'In the top five of a member who shares your taste',
    es: 'En el top de un miembro con tus gustos',
    ar: 'في قائمة عضو يشاركك الذوق',
  },
  'raison.voisins': {
    fr: 'Dans le top de {nombre} membres qui partagent vos goûts',
    en: 'In the top five of {nombre} members who share your taste',
    es: 'En el top de {nombre} miembros con tus gustos',
    ar: 'في قوائم {nombre} أعضاء يشاركونك الذوق',
  },
  'raison.proche_distance': {
    fr: 'Empreinte très proche de vos coups de cœur (à {distance} points)',
    en: 'Cultural fingerprint very close to your favourites ({distance} points away)',
    es: 'Huella muy cercana a tus favoritos (a {distance} puntos)',
    ar: 'بصمة قريبة جدًّا من مفضّلاتك (على مسافة {distance} نقطة)',
  },
  'raison.proche': {
    fr: 'Empreinte très proche de vos coups de cœur',
    en: 'Cultural fingerprint very close to your favourites',
    es: 'Huella muy cercana a tus favoritos',
    ar: 'بصمة قريبة جدًّا من مفضّلاتك',
  },
  'raison.communs': {
    fr: 'Comme vos coups de cœur : {communs}',
    en: 'Like your favourites: {communs}',
    es: 'Como tus favoritos: {communs}',
    ar: 'مثل مفضّلاتك: {communs}',
  },
  'raison.defaut': {
    fr: 'Proche de ce que vous avez aimé',
    en: 'Close to what you loved',
    es: 'Cercana a lo que te ha gustado',
    ar: 'قريب من الذي أحببته',
  },

  // --- La fiche d'une œuvre ---------------------------------------------
  'fiche.erreur': {
    fr: 'Cette fiche ne répond pas — réessayez dans un instant.',
    en: 'This page is not responding — try again in a moment.',
    es: 'Esta ficha no responde: inténtalo de nuevo en un momento.',
    ar: 'هذه الصفحة لا تستجيب — أعد المحاولة بعد لحظات.',
  },
  'fiche.agrandir_affiche': { fr: "Agrandir l'affiche", en: 'Enlarge the poster', es: 'Ampliar el cartel', ar: 'تكبير الملصق' },
  'fiche.ecrit_par': { fr: 'Écrit par', en: 'Written by', es: 'Escrito por', ar: 'من تأليف' },
  'fiche.realise_par': { fr: 'Réalisé et créé par', en: 'Directed and created by', es: 'Dirigido y creado por', ar: 'من إخراج وإبداع' },
  'fiche.distribution': { fr: "À l'affiche", en: 'Cast', es: 'Reparto', ar: 'طاقم التمثيل' },
  'fiche.ou_regarder': { fr: 'Où regarder', en: 'Where to watch', es: 'Dónde verlo', ar: 'أين تشاهده' },
  'fiche.ailleurs': {
    fr: 'Rien dans votre pays — mais disponible dans {nombre} autres.',
    en: 'Nothing in your country — but available in {nombre} others.',
    es: 'Nada en tu país, pero disponible en {nombre} más.',
    ar: 'غير متوفّر في بلدك — لكنه متوفّر في {nombre} بلدان أخرى.',
  },
  'fiche.ailleurs_un': {
    fr: 'Rien dans votre pays — mais disponible dans un autre.',
    en: 'Nothing in your country — but available in one other.',
    es: 'Nada en tu país, pero disponible en otro.',
    ar: 'غير متوفّر في بلدك — لكنه متوفّر في بلد آخر.',
  },
  'fiche.source_offres': {
    fr: 'Offres et disponibilité — JustWatch',
    en: 'Offers and availability — JustWatch',
    es: 'Ofertas y disponibilidad — JustWatch',
    ar: 'العروض والتوفّر — JustWatch',
  },
  'offre.flatrate': { fr: 'Par abonnement', en: 'With a subscription', es: 'Con suscripción', ar: 'بالاشتراك' },
  'offre.free': { fr: 'Gratuit', en: 'Free', es: 'Gratis', ar: 'مجانًا' },
  'offre.ads': { fr: 'Gratuit avec publicité', en: 'Free with ads', es: 'Gratis con publicidad', ar: 'مجانًا مع إعلانات' },
  'offre.rent': { fr: 'En location', en: 'To rent', es: 'En alquiler', ar: 'للإيجار' },
  'offre.buy': { fr: "À l'achat", en: 'To buy', es: 'En compra', ar: 'للشراء' },
  'fiche.videos': { fr: 'Bandes-annonces', en: 'Trailers', es: 'Tráileres', ar: 'المقاطع الدعائية' },
  'fiche.saisons': { fr: 'Les saisons', en: 'Seasons', es: 'Temporadas', ar: 'المواسم' },
  'fiche.compte_saisons': { fr: '{nombre} saisons', en: '{nombre} seasons', es: '{nombre} temporadas', ar: '{nombre} مواسم' },
  'fiche.compte_saison': { fr: '{nombre} saison', en: '1 season', es: '1 temporada', ar: 'موسم واحد' },
  'fiche.compte_episodes': { fr: '{nombre} épisodes', en: '{nombre} episodes', es: '{nombre} episodios', ar: '{nombre} حلقة' },
  'fiche.filmographie': { fr: 'Voir les œuvres de {nom}', en: 'See the works of {nom}', es: 'Ver las obras de {nom}', ar: 'عرض أعمال {nom}' },

  // --- Les saisons ------------------------------------------------------
  'saison.titre': { fr: 'Saison {numero}', en: 'Season {numero}', es: 'Temporada {numero}', ar: 'الموسم {numero}' },
  'saison.chargement': { fr: 'Chargement des épisodes…', en: 'Loading episodes…', es: 'Cargando episodios…', ar: 'جارٍ تحميل الحلقات…' },
  'saison.vide': {
    fr: 'Les épisodes de cette saison ne sont pas encore collectés.',
    en: 'The episodes of this season have not been collected yet.',
    es: 'Los episodios de esta temporada aún no se han recopilado.',
    ar: 'لم تُجمَع حلقات هذا الموسم بعد.',
  },
  'saison.erreur': {
    fr: 'Les épisodes ne répondent pas — refermez et réessayez.',
    en: 'Episodes are not responding — close this and try again.',
    es: 'Los episodios no responden: cierra y vuelve a intentarlo.',
    ar: 'الحلقات لا تستجيب — أغلِق ثم أعد المحاولة.',
  },
  'saison.episode_sans_titre': { fr: 'Épisode sans titre', en: 'Untitled episode', es: 'Episodio sin título', ar: 'حلقة بلا عنوان' },

  // --- Les vidéos -------------------------------------------------------
  'video.lire': { fr: 'Lire ici', en: 'Play here', es: 'Reproducir aquí', ar: 'شغّل هنا' },
  'video.ouvrir': { fr: 'Ouvrir sur {site}', en: 'Open on {site}', es: 'Abrir en {site}', ar: 'افتح على {site}' },
  'video.lecteur': { fr: 'Lecteur vidéo : {nom}', en: 'Video player: {nom}', es: 'Reproductor de vídeo: {nom}', ar: 'مشغّل الفيديو: {nom}' },
  'video.fermer': { fr: 'Fermer le lecteur', en: 'Close the player', es: 'Cerrar el reproductor', ar: 'إغلاق المشغّل' },

  // --- Quelqu'un : portrait et filmographie -----------------------------
  'personne.inconnue': { fr: 'Quelqu’un', en: 'Someone', es: 'Alguien', ar: 'شخص' },
  'personne.agrandir': { fr: 'Agrandir le portrait', en: 'Enlarge the portrait', es: 'Ampliar el retrato', ar: 'تكبير الصورة' },
  'personne.compte': { fr: '{nombre} œuvres au catalogue', en: '{nombre} works in the catalogue', es: '{nombre} obras en el catálogo', ar: '{nombre} عملًا في الفهرس' },
  'personne.compte_une': {
    fr: '{nombre} œuvre au catalogue',
    en: '1 work in the catalogue',
    es: '1 obra en el catálogo',
    ar: 'عمل واحد في الفهرس',
  },
  'personne.aucune': {
    fr: 'Aucune œuvre trouvée au catalogue',
    en: 'No work found in the catalogue',
    es: 'Ninguna obra encontrada en el catálogo',
    ar: 'لم يُعثَر على أي عمل في الفهرس',
  },
  'personne.par_le_nom': {
    fr: ' — trouvées par le nom, dans les {univers} seulement',
    en: ' — found by name, in {univers} only',
    es: ' — encontradas por el nombre, solo en {univers}',
    ar: ' — عُثر عليها بالاسم، في {univers} فقط',
  },
  'personne.erreur': {
    fr: 'Cette filmographie ne répond pas — réessayez dans un instant.',
    en: 'This filmography is not responding — try again in a moment.',
    es: 'Esta filmografía no responde: inténtalo de nuevo en un momento.',
    ar: 'قائمة الأعمال لا تستجيب — أعد المحاولة بعد لحظات.',
  },
  'personne.ouvrir': { fr: 'Ouvrir la fiche de {titre}', en: 'Open the page for {titre}', es: 'Abrir la ficha de {titre}', ar: 'افتح صفحة {titre}' },
  'personne.pages': { fr: 'Pages de la filmographie', en: 'Filmography pages', es: 'Páginas de la filmografía', ar: 'صفحات قائمة الأعمال' },
  'personne.precedentes': { fr: '← Précédentes', en: '← Previous', es: '← Anteriores', ar: 'السابقة →' },
  'personne.suivantes': { fr: 'Suivantes →', en: 'Next →', es: 'Siguientes →', ar: '← التالية' },
  'role.interpretation': { fr: 'Interprétation', en: 'Acting', es: 'Interpretación', ar: 'تمثيل' },
  'role.realisation': { fr: 'Réalisation', en: 'Directing', es: 'Dirección', ar: 'إخراج' },
  'role.creation': { fr: 'Création', en: 'Creator', es: 'Creación', ar: 'ابتكار' },
  'role.auteur': { fr: 'Auteur', en: 'Author', es: 'Autor', ar: 'تأليف' },

  // --- Ma liste : ce qui a été classé ------------------------------------
  'liste.a_voir': { fr: 'À voir', en: 'Want to see', es: 'Por ver', ar: 'للمشاهدة' },
  'liste.aime': { fr: 'Vus & aimés', en: 'Seen & loved', es: 'Vistos y preferidos', ar: 'شاهدتها وأحببتها' },
  'liste.aime_pas': { fr: 'Pas pour moi', en: 'Not for me', es: 'No me gustan', ar: 'لا تعجبني' },
  'liste.vide': {
    fr: "Vous n'avez encore rien classé. Cherchez une œuvre, dites ce que vous en pensez — et elle apparaît ici.",
    en: 'You have not sorted anything yet. Search for a work, say what you think of it — and it lands here.',
    es: 'Todavía no has clasificado nada. Busca una obra, di qué te parece, y aparecerá aquí.',
    ar: 'لم تصنّف شيئًا بعد. ابحث عن عمل وقل رأيك فيه — وسيظهر هنا.',
  },
  'liste.vide_section': { fr: 'Rien ici pour le moment.', en: 'Nothing here yet.', es: 'Nada aquí por ahora.', ar: 'لا شيء هنا بعد.' },
  'liste.erreur': {
    fr: 'Votre liste ne répond pas — réessayez dans un instant.',
    en: 'Your list is not responding — try again in a moment.',
    es: 'Tu lista no responde: inténtalo de nuevo en un momento.',
    ar: 'قائمتك لا تستجيب — أعد المحاولة بعد لحظات.',
  },
  'liste.tous_univers': {
    fr: 'Tous les univers confondus — ce que vous avez classé ne se range pas par onglet.',
    en: 'All universes together — what you sorted is not filed by tab.',
    es: 'Todos los universos juntos: lo que has clasificado no se ordena por pestaña.',
    ar: 'كل العوالم مجتمعة — ما صنّفته ليس مرتّبًا حسب التبويب.',
  },
  'liste.compte': { fr: '{nombre} œuvres', en: '{nombre} works', es: '{nombre} obras', ar: '{nombre} عملًا' },
  'liste.compte_une': { fr: '{nombre} œuvre', en: '1 work', es: '1 obra', ar: 'عمل واحد' },
} satisfies Record<string, Phrase>

export type CleTexte = keyof typeof TEXTES

/** Le rendu d'une clé dans une langue, valeurs interpolées.
 *
 *  Une clé absente rend la clé elle-même : sur une page, un `liste.compte`
 *  cru se remarque immédiatement, là qu'une chaîne vide passerait inaperçue. */
export function traduire(langue: Langue, cle: CleTexte, valeurs?: Valeurs): string {
  const phrase = TEXTES[cle]
  if (!phrase) return cle
  const texte = phrase[langue] ?? phrase[LANGUE_DEFAUT]
  if (!valeurs) return texte
  return texte.replace(/\{(\w+)\}/g, (entier, nom: string) =>
    nom in valeurs ? String(valeurs[nom]) : entier,
  )
}

/** Ce qu'un composant tient : la langue, son sens, et de quoi écrire. */
export interface Textes {
  langue: Langue
  sens: 'ltr' | 'rtl'
  /** Une phrase. */
  dit(cle: CleTexte, valeurs?: Valeurs): string
  /** Un nombre dans la langue — l'arabe a ses propres chiffres selon la
   *  locale, et le français son espace insécable des milliers. */
  nombre(valeur: number): string
  /** Le singulier ou le pluriel, `{nombre}` déjà formaté.
   *
   *  Deux formes seulement : c'est juste pour le français, l'anglais et
   *  l'espagnol, et approché pour l'arabe, qui en compte six. Le prix de
   *  l'approximation est une phrase parfois raide, jamais fausse.
   *
   *  Le ZÉRO n'est pas traité pareil partout : « 0 œuvre » est au singulier
   *  en français, « 0 works » au pluriel en anglais. Vu à l'écran — la
   *  section vide de « Ma liste » affichait « 0 œuvres ». */
  compte(valeur: number, une: CleTexte, plusieurs: CleTexte, valeurs?: Valeurs): string
}

/** Le nombre prend-il le singulier dans cette langue ? */
function au_singulier(langue: Langue, valeur: number): boolean {
  // Le français range le zéro avec le singulier ; les trois autres langues
  // servies ne réservent le singulier qu'à l'unité.
  return langue === 'fr' ? valeur < 2 : valeur === 1
}

export function textes(langue: Langue): Textes {
  const format = new Intl.NumberFormat(LANGUE_LOCALES[langue])
  return {
    langue,
    sens: LANGUE_SENS[langue],
    dit: (cle, valeurs) => traduire(langue, cle, valeurs),
    nombre: (valeur) => format.format(valeur),
    compte: (valeur, une, plusieurs, valeurs) =>
      traduire(langue, au_singulier(langue, valeur) ? une : plusieurs, {
        nombre: format.format(valeur),
        ...valeurs,
      }),
  }
}
