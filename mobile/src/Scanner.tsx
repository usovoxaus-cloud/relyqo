import { useRef, useState } from 'react';
import { KeyboardAvoidingView, Linking, Platform, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Icon } from './Icon';
import { readVisitToken } from './navigation';
import type { Copy } from './strings';

export function Scanner({ copy, active, onClose, onToken }: { copy: Copy; active: boolean; onClose: () => void; onToken: (token: string) => void }) {
  const [permission, requestPermission] = useCameraPermissions();
  const [manual, setManual] = useState(false);
  const [code, setCode] = useState('');
  const [error, setError] = useState('');
  const [cameraFailed, setCameraFailed] = useState(false);
  const [torch, setTorch] = useState(false);
  const accepted = useRef(false);
  const lastScan = useRef(0);

  function accept(value: string, camera = false) {
    if (accepted.current || (camera && Date.now() - lastScan.current < 1500)) return;
    lastScan.current = Date.now();
    const token = readVisitToken(value);
    if (!token) { setError(copy.invalidQr); return; }
    accepted.current = true;
    setCode('');
    onToken(token);
  }

  return <SafeAreaView style={styles.screen}>
    <View style={styles.header}><Text style={styles.title}>{copy.scanTitle}</Text><Pressable accessibilityRole="button" accessibilityLabel={copy.close} onPress={onClose} style={styles.iconButton}><Icon name="close" color="#f0f8f7"/></Pressable></View>
    <KeyboardAvoidingView style={styles.grow} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
      <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
        <Text style={styles.body}>{copy.scanHint}</Text>
        {!manual && !cameraFailed && permission?.granted && active ? <View style={styles.preview}>
          <CameraView style={StyleSheet.absoluteFill} facing="back" enableTorch={torch} barcodeScannerSettings={{ barcodeTypes: ['qr'] }} onBarcodeScanned={({ data }) => accept(data, true)} onMountError={() => { setCameraFailed(true); setError(copy.cameraFailed); }}/>
          <View pointerEvents="none" style={styles.frame}/>
          <Pressable accessibilityRole="button" accessibilityState={{ selected: torch }} style={styles.torch} onPress={() => setTorch(!torch)}><Text style={styles.light}>{copy.torch}</Text></Pressable>
        </View> : !manual && !cameraFailed && <View style={styles.permission}>
          <Icon name="qr" size={56} color="#76e4c0"/>
          <Text style={styles.body}>{permission && !permission.canAskAgain ? copy.denied : copy.cameraHint}</Text>
          <Pressable accessibilityRole="button" style={styles.button} onPress={async () => {
            try { if (permission && !permission.canAskAgain) await Linking.openSettings(); else await requestPermission(); }
            catch { setError(copy.cameraFailed); }
          }}><Text style={styles.buttonText}>{permission && !permission.canAskAgain ? copy.openSettings : copy.allowCamera}</Text></Pressable>
        </View>}
        <Pressable accessibilityRole="button" onPress={() => { setManual(!manual); setTorch(false); }} style={styles.secondary}><Text style={styles.light}>{manual ? copy.allowCamera : copy.manual}</Text></Pressable>
        {(manual || cameraFailed || !permission?.granted) && <View style={styles.form}>
          <Text style={styles.label}>{copy.code}</Text>
          <TextInput accessibilityLabel={copy.code} style={styles.input} value={code} onChangeText={setCode} autoCorrect={false} autoCapitalize="none" maxLength={4096} multiline numberOfLines={3} placeholder={copy.code} placeholderTextColor="#7c929c"/>
          <Pressable accessibilityRole="button" disabled={!code.trim()} accessibilityState={{ disabled: !code.trim() }} onPress={() => accept(code)} style={[styles.button, !code.trim() && styles.disabled]}><Text style={styles.buttonText}>{copy.verify}</Text></Pressable>
        </View>}
        {!!error && <Text accessibilityRole="alert" style={styles.error}>{error}</Text>}
        <Text style={styles.note}>{copy.cameraHint}</Text>
      </ScrollView>
    </KeyboardAvoidingView>
  </SafeAreaView>;
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: '#071827' }, grow: { flex: 1 },
  header: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 20, paddingVertical: 10 },
  title: { color: '#f0f8f7', fontSize: 22, fontWeight: '700', flex: 1 },
  iconButton: { width: 48, height: 48, alignItems: 'center', justifyContent: 'center' },
  content: { padding: 20, gap: 18 }, body: { color: '#b7ccd0', fontSize: 16, lineHeight: 24 },
  preview: { height: 320, overflow: 'hidden', borderRadius: 24, backgroundColor: '#020d16', alignItems: 'center', justifyContent: 'center' },
  frame: { height: 220, width: 220, borderWidth: 3, borderColor: '#76e4c0', borderRadius: 24 },
  torch: { position: 'absolute', bottom: 12, backgroundColor: '#071827dd', paddingVertical: 12, paddingHorizontal: 20, borderRadius: 16 },
  permission: { backgroundColor: '#102c39', borderRadius: 24, padding: 24, gap: 20, alignItems: 'center' },
  form: { gap: 12 }, label: { color: '#b7ccd0', fontSize: 14 },
  input: { borderWidth: 1, borderColor: '#3b5767', color: '#fff', backgroundColor: '#0c2230', borderRadius: 14, minHeight: 90, padding: 14, fontSize: 16, textAlignVertical: 'top' },
  button: { backgroundColor: '#76e4c0', minHeight: 50, paddingHorizontal: 18, paddingVertical: 14, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  buttonText: { color: '#08281e', fontWeight: '700', fontSize: 15 },
  secondary: { minHeight: 48, alignItems: 'center', justifyContent: 'center' }, light: { color: '#d8f7ef', fontSize: 15, fontWeight: '600' },
  disabled: { opacity: 0.4 }, error: { color: '#ffb6c0', fontSize: 15, lineHeight: 22 },
  note: { color: '#849ea8', fontSize: 13, lineHeight: 20 },
});
