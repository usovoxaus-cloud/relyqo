import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ActivityIndicator, Alert, AppState, BackHandler, Keyboard, Linking, Modal, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { getLocales } from 'expo-localization';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { WebView } from 'react-native-webview';
import type { WebViewMessageEvent, WebViewNavigation } from 'react-native-webview';
import { MOBILE_BRIDGE, deliverQrScript } from './src/bridge';
import { Icon } from './src/Icon';
import { Scanner } from './src/Scanner';
import { strings } from './src/strings';
import { ORIGIN, isInternalUrl, languageFromUrl, navigationKind, tabForUrl, tabUrl, withLanguage } from './src/navigation';
import type { Language, Tab } from './src/navigation';

const LANGUAGE_KEY = 'relyqo.mobile.language';
const tabs: Tab[] = ['search', 'qr', 'top', 'account'];

export default function App() {
  return <SafeAreaProvider><MobileApp/></SafeAreaProvider>;
}

function MobileApp() {
  const web = useRef<WebView>(null);
  const [language, setLanguage] = useState<Language>(() => getLocales()[0]?.languageCode === 'uz' ? 'uz' : 'ru');
  const [initialized, setInitialized] = useState(false);
  const [uri, setUri] = useState(tabUrl('search', language));
  const currentUrl = useRef(uri);
  const [tab, setTab] = useState<Tab>('search');
  const [webKey, setWebKey] = useState(0);
  const [canGoBack, setCanGoBack] = useState(false);
  const [loading, setLoading] = useState(true);
  const [slow, setSlow] = useState(false);
  const [failed, setFailed] = useState(false);
  const [scanner, setScanner] = useState(false);
  const [menu, setMenu] = useState(false);
  const [keyboard, setKeyboard] = useState(false);
  const [active, setActive] = useState(AppState.currentState === 'active');
  const pendingQr = useRef<string | null>(null);
  const externalPrompt = useRef(false);
  const copy = strings[language];
  const source = useMemo(() => ({ uri }), [uri]);

  const navigate = useCallback((url: string, keepQr = false) => {
    if (!isInternalUrl(url)) return;
    if (!keepQr) pendingQr.current = null;
    setMenu(false); setFailed(false); setLoading(true); setCanGoBack(false);
    setTab(tabForUrl(url)); currentUrl.current = url;
    if (url === uri) setWebKey(key => key + 1);
    else setUri(url);
  }, [uri]);

  useEffect(() => {
    let alive = true;
    AsyncStorage.getItem(LANGUAGE_KEY).then(saved => {
      if (alive && (saved === 'ru' || saved === 'uz')) { setLanguage(saved); setUri(tabUrl('search', saved)); currentUrl.current = tabUrl('search', saved); }
    }).catch(() => {}).finally(() => { if (alive) setInitialized(true); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const app = AppState.addEventListener('change', state => setActive(state === 'active'));
    const show = Keyboard.addListener('keyboardDidShow', () => setKeyboard(true));
    const hide = Keyboard.addListener('keyboardDidHide', () => setKeyboard(false));
    return () => { app.remove(); show.remove(); hide.remove(); };
  }, []);

  useEffect(() => {
    const listener = BackHandler.addEventListener('hardwareBackPress', () => {
      if (scanner) { setScanner(false); return true; }
      if (menu) { setMenu(false); return true; }
      if (canGoBack) { web.current?.goBack(); return true; }
      if (tab !== 'search') { navigate(tabUrl('search', language)); return true; }
      return false;
    });
    return () => listener.remove();
  }, [canGoBack, scanner, menu, tab, language, navigate]);

  useEffect(() => {
    if (!loading || !initialized) { setSlow(false); return; }
    const wake = setTimeout(() => setSlow(true), 12000);
    const timeout = setTimeout(() => { web.current?.stopLoading(); setFailed(true); setLoading(false); }, 90000);
    return () => { clearTimeout(wake); clearTimeout(timeout); };
  }, [loading, initialized, webKey, uri]);


  function rememberLanguage(value: Language) {
    setLanguage(value);
    AsyncStorage.setItem(LANGUAGE_KEY, value).catch(() => {});
  }

  function navigationChanged(state: WebViewNavigation) {
    if (!isInternalUrl(state.url)) return;
    currentUrl.current = state.url;
    setCanGoBack(state.canGoBack);
    setTab(tabForUrl(state.url));
    const value = languageFromUrl(state.url);
    if (value && value !== language) rememberLanguage(value);
  }

  function openExternal(url: string) {
    if (navigationKind(url) === 'blocked' || externalPrompt.current) return;
    externalPrompt.current = true;
    const clear = () => { externalPrompt.current = false; };
    Alert.alert(copy.external, new URL(url).protocol.startsWith('http') ? new URL(url).host : url.slice(0, 150), [
      { text: copy.cancel, style: 'cancel', onPress: clear },
      { text: copy.open, onPress: () => { clear(); Linking.openURL(url).catch(() => Alert.alert(copy.linkFailed)); } },
    ], { cancelable: true, onDismiss: clear });
  }

  function onMessage(event: WebViewMessageEvent) {
    if (!isInternalUrl(event.nativeEvent.url) || event.nativeEvent.data.length > 512) return;
    try {
      const message = JSON.parse(event.nativeEvent.data);
      if (!message || typeof message !== 'object') return;
      if (message.type === 'scan') { setScanner(true); return; }
      if (message.type !== 'ready') return;
      if (message.language === 'ru' || message.language === 'uz') rememberLanguage(message.language);
      // A queued scan is delivered once, to the rating page only; never put it in a URL, log or disk storage.
      const path = new URL(event.nativeEvent.url).pathname;
      if (pendingQr.current && ['/', '/consumer'].includes(path)) {
        const token = pendingQr.current;
        pendingQr.current = null;
        web.current?.injectJavaScript(deliverQrScript(token));
      }
    } catch { /* Ignore unknown messages; no privileged bridge commands exist. */ }
  }

  function receiveToken(token: string) {
    setScanner(false);
    pendingQr.current = token;
    navigate(tabUrl('qr', language), true);
  }

  function pageFailed() { setFailed(true); setLoading(false); }

  return <SafeAreaView style={styles.root} edges={['top', 'left', 'right', 'bottom']}>
    <StatusBar style="light"/>
    <View style={styles.header}>
      {canGoBack ? <Pressable accessibilityRole="button" accessibilityLabel={copy.back} onPress={() => web.current?.goBack()} style={styles.iconButton}><Icon name="back" color="#eaf9f4"/></Pressable> : <View style={styles.mark}><Text style={styles.markText}>R</Text></View>}
      <View style={styles.brand}><Text style={styles.brandText}>RELYQO</Text><Text style={styles.country}>{copy.country}</Text></View>
      <Pressable accessibilityRole="button" accessibilityLabel={copy.language} style={styles.language} onPress={() => {
        const next = language === 'ru' ? 'uz' : 'ru'; rememberLanguage(next); navigate(withLanguage(currentUrl.current, next));
      }}><Text style={styles.languageText}>{language.toUpperCase()}</Text></Pressable>
      <Pressable accessibilityRole="button" accessibilityLabel={copy.settings} style={styles.iconButton} onPress={() => setMenu(true)}><Icon name="menu" color="#eaf9f4"/></Pressable>
    </View>
    <View style={styles.content}>
      {initialized && <WebView ref={web} key={webKey} source={source} style={styles.web}
        applicationNameForUserAgent="RELYQOMobile/1.0"
        originWhitelist={['*']} onShouldStartLoadWithRequest={request => {
          // '*' deliberately delegates every scheme to this explicit policy instead
          // of WebView's default, which opens unmatched origins in other apps.
          const kind = navigationKind(request.url);
          if (kind === 'internal') return true;
          if (kind === 'external' && request.isTopFrame !== false) openExternal(request.url);
          return false;
        }}
        onOpenWindow={({ nativeEvent }) => {
          if (isInternalUrl(nativeEvent.targetUrl)) navigate(nativeEvent.targetUrl);
          else openExternal(nativeEvent.targetUrl);
        }}
        onNavigationStateChange={navigationChanged} onMessage={onMessage}
        injectedJavaScript={MOBILE_BRIDGE}
        onLoadStart={() => { setLoading(true); setFailed(false); }}
        onLoad={() => { setLoading(false); setFailed(false); }}
        onError={pageFailed} onHttpError={({ nativeEvent }) => { if (nativeEvent.statusCode >= 400 && nativeEvent.url === currentUrl.current) pageFailed(); }}
        onContentProcessDidTerminate={pageFailed} onRenderProcessGone={pageFailed}
        javaScriptCanOpenWindowsAutomatically={false} setSupportMultipleWindows
        mixedContentMode="never" allowFileAccess={false} allowFileAccessFromFileURLs={false}
        allowUniversalAccessFromFileURLs={false} thirdPartyCookiesEnabled={false}
        sharedCookiesEnabled={false} webviewDebuggingEnabled={false}
        domStorageEnabled cacheEnabled allowsInlineMediaPlayback mediaPlaybackRequiresUserAction
        geolocationEnabled allowsBackForwardNavigationGestures={Platform.OS === 'ios'}
        contentInsetAdjustmentBehavior="never" automaticallyAdjustContentInsets={false}
      />}
      {(loading || !initialized) && !failed && <View style={styles.loading} accessibilityLiveRegion="polite"><ActivityIndicator color="#76e4c0"/><Text style={styles.loadingText}>{slow ? copy.slow : copy.loading}</Text></View>}
      {failed && <View style={styles.failure}>
        <View style={styles.errorMark}><Icon name="refresh" size={36} color="#76e4c0"/></View>
        <Text style={styles.errorTitle}>{copy.failed}</Text><Text style={styles.errorBody}>{copy.offline}</Text>
        <Pressable accessibilityRole="button" style={styles.primary} onPress={() => navigate(currentUrl.current, true)}><Text style={styles.primaryText}>{copy.retry}</Text></Pressable>
        <Pressable accessibilityRole="button" style={styles.textButton} onPress={() => openExternal(currentUrl.current)}><Text style={styles.lightText}>{copy.browser}</Text></Pressable>
      </View>}
    </View>
    {!keyboard && <View style={styles.tabs} accessibilityRole="tablist">{tabs.map(item => <Pressable key={item} accessibilityRole="tab" accessibilityLabel={copy[item]} accessibilityState={{ selected: item === tab }} style={styles.tab} onPress={() => item === 'qr' ? setScanner(true) : navigate(tabUrl(item, language))}>
      <View style={[styles.tabIcon, item === tab && styles.activeIcon]}><Icon name={item} color={item === tab ? '#76e4c0' : '#8aa1aa'}/></View>
      <Text style={[styles.tabText, item === tab && styles.activeText]}>{copy[item]}</Text>
    </Pressable>)}</View>}
    <Modal visible={scanner} animationType="slide" presentationStyle="fullScreen" onRequestClose={() => setScanner(false)}>{scanner && <Scanner copy={copy} active={active} onClose={() => setScanner(false)} onToken={receiveToken}/>}</Modal>
    <Modal visible={menu} animationType="slide" presentationStyle="pageSheet" onRequestClose={() => setMenu(false)}>
      <SafeAreaView style={styles.root}><View style={styles.menuHeader}><Text style={styles.brandText}>RELYQO</Text><Pressable accessibilityRole="button" accessibilityLabel={copy.close} style={styles.iconButton} onPress={() => setMenu(false)}><Icon name="close" color="#fff"/></Pressable></View>
        <ScrollView contentContainerStyle={styles.menuContent}><Text style={styles.errorBody}>{copy.about}</Text>
          {[[copy.business, '/business-owner'], [copy.admin, '/admin'], [copy.privacy, '/privacy'], [copy.terms, '/terms']].map(([label, path]) => <Pressable key={path} accessibilityRole="button" style={styles.menuItem} onPress={() => navigate(withLanguage(ORIGIN + path, language))}><Text style={styles.lightText}>{label}</Text><Text style={styles.arrow}>›</Text></Pressable>)}
          <Pressable accessibilityRole="button" style={styles.menuItem} onPress={() => navigate(currentUrl.current)}><Text style={styles.lightText}>{copy.refresh}</Text><Icon name="refresh" color="#76e4c0"/></Pressable>
          <Text style={styles.version}>{copy.preview}</Text>
        </ScrollView>
      </SafeAreaView>
    </Modal>
  </SafeAreaView>;
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#071827' }, content: { flex: 1 }, web: { flex: 1, backgroundColor: '#071827' },
  header: { flexDirection: 'row', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 8, gap: 10, borderBottomWidth: 1, borderBottomColor: '#163342' },
  mark: { width: 36, height: 36, borderRadius: 12, backgroundColor: '#76e4c0', justifyContent: 'center', alignItems: 'center' }, markText: { color: '#06281f', fontSize: 24, fontWeight: '900' },
  brand: { flex: 1 }, brandText: { color: '#f0faf7', fontSize: 16, fontWeight: '800', letterSpacing: 1.5 }, country: { color: '#8fa9b2', fontSize: 11, marginTop: 3 },
  iconButton: { height: 44, width: 44, justifyContent: 'center', alignItems: 'center' },
  language: { minWidth: 44, height: 44, alignItems: 'center', justifyContent: 'center' }, languageText: { color: '#b9e7d9', fontSize: 13, fontWeight: '700' },
  loading: { position: 'absolute', top: 0, left: 0, right: 0, padding: 14, flexDirection: 'row', gap: 12, backgroundColor: '#102c39f5', alignItems: 'center' }, loadingText: { color: '#c7e6dd', fontSize: 13, lineHeight: 19, flex: 1 },
  failure: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: '#071827', justifyContent: 'center', alignItems: 'center', padding: 28, gap: 18 },
  errorMark: { padding: 22, borderRadius: 30, backgroundColor: '#102c39' }, errorTitle: { color: '#f0faf7', fontSize: 24, fontWeight: '700', textAlign: 'center' },
  errorBody: { color: '#9fb7c2', fontSize: 16, lineHeight: 24 }, primary: { paddingVertical: 15, paddingHorizontal: 30, minHeight: 50, backgroundColor: '#76e4c0', borderRadius: 15 }, primaryText: { color: '#06281f', fontSize: 16, fontWeight: '700' },
  textButton: { padding: 14, minHeight: 48 }, lightText: { color: '#d6f0e9', fontSize: 16 },
  tabs: { flexDirection: 'row', borderTopWidth: 1, borderTopColor: '#163342', paddingTop: 6, paddingBottom: 4 }, tab: { flex: 1, alignItems: 'center', paddingVertical: 6, gap: 4 },
  tabIcon: { borderRadius: 15, paddingVertical: 5, paddingHorizontal: 16 }, activeIcon: { backgroundColor: '#123e36' }, tabText: { color: '#8aa1aa', fontSize: 11, fontWeight: '600' }, activeText: { color: '#76e4c0' },
  menuHeader: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', padding: 20 }, menuContent: { padding: 24, gap: 18 }, menuItem: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', minHeight: 56, paddingVertical: 12, borderBottomColor: '#213d4c', borderBottomWidth: 1 }, arrow: { color: '#76e4c0', fontSize: 24 }, version: { color: '#829da6', fontSize: 13, marginTop: 18 },
});
