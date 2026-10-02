import com.sun.tools.attach.VirtualMachine;

/** Loads the probe into a running Fakturama: java Attach PID probe.jar OUTPUT_FILE */
public final class Attach {
    public static void main(String[] args) throws Exception {
        VirtualMachine vm = VirtualMachine.attach(args[0]);
        try {
            vm.loadAgent(args[1], args[2]);
        } finally {
            vm.detach();
        }
    }
}
